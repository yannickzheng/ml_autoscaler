#!/usr/bin/env python3
"""
ML-based Autoscaler pour NexSlice (Version Optimisée)
Approche: Time-Series Forecasting avec Random Forest
"""

import time
import logging
import numpy as np
from collections import deque
from datetime import datetime
from kubernetes import client, config
from prometheus_api_client import PrometheusConnect
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler

# Configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - [%(levelname)s] - %(message)s')
logger = logging.getLogger("ML-Autoscaler")

# Paramètres ML
WINDOW_SIZE = 5  # Fenêtre d'historique (5 mesures)
PREDICTION_HORIZON = 2  # Prédiction à t+2
MIN_TRAINING_DATA = 20  # Données min pour entrainement
MAX_HISTORY = 1000  # Taille buffer mémoire


class MetricsCollector:
    """Collecte optimisée des métriques Prometheus"""

    def __init__(self, url="http://prometheus:9090"):
        self.prom = PrometheusConnect(url=url, disable_ssl=True)

    def get_current_metrics(self):
        """Récupère toutes les métriques en une passe"""
        m = {'cpu': 0.0, 'memory': 0.0, 'latency': 0.0, 'throughput': 0.0}
        try:
            # Latence (ms)
            data = self.prom.custom_query('probe_duration_seconds{job="blackbox"}')
            if data: m['latency'] = float(data[0]['value'][1]) * 1000

            # Throughput (MB/s) - Normalisé
            data = self.prom.custom_query('sum(rate(container_network_transmit_bytes_total{namespace="nexslice"}[5m]))')
            if data: m['throughput'] = float(data[0]['value'][1]) / (1024 * 1024)

            # CPU (%) - Moyenne des VNFs
            data = self.prom.custom_query(
                'avg(rate(container_cpu_usage_seconds_total{pod=~".*smf.*|.*upf.*"}[5m])) * 100')
            if data: m['cpu'] = float(data[0]['value'][1])

            # Mémoire (%)
            data = self.prom.custom_query(
                'avg(container_memory_usage_bytes{pod=~".*smf.*|.*upf.*"} / container_spec_memory_limit_bytes) * 100')
            if data: m['memory'] = float(data[0]['value'][1])

            return m
        except Exception as e:
            logger.error(f"Erreur métriques: {e}")
            return m


class TimeSeriesPredictor:
    """Moteur de prédiction ML (Sliding Window + Random Forest)"""

    def __init__(self):
        self.model = RandomForestRegressor(n_estimators=50, n_jobs=-1, random_state=42) #on crée 50 arbres de décision qui vont voter
        self.scaler = StandardScaler()
        self.history = deque(maxlen=MAX_HISTORY)
        self.is_trained = False

    def _calculate_score(self, m):
        """Calcul du score de charge composite (Target)"""
        # Formule pondérée spécifique 5G
        return (0.3 * m['cpu'] +
                0.2 * m['memory'] +
                0.3 * min(100, m['latency']) +  # Latence critique
                0.2 * min(100, m['throughput']))

    def update_and_predict(self, metrics):
        """Pipeline complet: Stockage -> Entrainement -> Prédiction"""
        score = self._calculate_score(metrics)

        # 1. Stockage: [cpu, mem, lat, through, score]
        record = [metrics['cpu'], metrics['memory'], metrics['latency'], metrics['throughput'], score]
        self.history.append(record)

        # 2. Entrainement (périodique)
        if len(self.history) >= MIN_TRAINING_DATA and len(self.history) % 10 == 0:
            self._train()

        # 3. Prédiction
        return score, self._predict_next()

    def _train(self):
        try:
            data = np.array(self.history)
            x, y = [], []

            # Création des séquences temporelles (Sliding Window)
            for i in range(WINDOW_SIZE, len(data) - PREDICTION_HORIZON):
                x.append(data[i - WINDOW_SIZE:i].flatten())  # Input: fenêtre passée
                y.append(data[i + PREDICTION_HORIZON][4])  # Target: score futur

            if len(x) > 10:
                x_scaled = self.scaler.fit_transform(x)
                self.model.fit(x_scaled, y)
                self.is_trained = True
                logger.info(f"Modèle ré-entraîné (R2: {self.model.score(x_scaled, y):.2f})")
        except Exception as e:
            logger.error(f"Erreur entrainement: {e}")

    def _predict_next(self):
        if not self.is_trained or len(self.history) < WINDOW_SIZE:
            return None
        try:
            # Prédiction sur la fenêtre courante
            current_window = np.array(self.history)[-WINDOW_SIZE:].flatten().reshape(1, -1)
            X_scaled = self.scaler.transform(current_window)
            return max(0, self.model.predict(X_scaled)[0])
        except Exception:
            return None


class Autoscaler:
    """Gestionnaire de Scaling Kubernetes"""

    def __init__(self, ns="nexslice"):
        self.ns = ns
        self.collector = MetricsCollector()
        self.predictor = TimeSeriesPredictor()

        try:
            config.load_incluster_config()
        except:
            config.load_kube_config()
        self.api = client.AppsV1Api()

        self.min_replicas = 2
        self.max_replicas = 10
        self.target_load = 60.0
        self.last_scale = datetime.min

    def scale_deployment(self, name, replicas):
        """Application du scaling via API K8s"""
        if (datetime.now() - self.last_scale).total_seconds() < 45: return  # Cooldown

        try:
            replicas = int(max(self.min_replicas, min(self.max_replicas, replicas)))
            current = self.api.read_namespaced_deployment(name, self.ns).spec.replicas

            if replicas != current:
                logger.info(f"⚖️ SCALING {name}: {current} -> {replicas}")
                self.api.patch_namespaced_deployment(name, self.ns, {'spec': {'replicas': replicas}})
                self.last_scale = datetime.now()
        except Exception as e:
            logger.error(f"Erreur scaling {name}: {e}")

    def run(self):
        logger.info("Démarrage Autoscaler ML (Mode Production)")
        while True:
            # Cycle principal
            m = self.collector.get_current_metrics()
            current_score, predicted_score = self.predictor.update_and_predict(m)

            log = f"Load: {current_score:.1f}% | Lat: {m['latency']:.0f}ms | CPU: {m['cpu']:.0f}%"

            if predicted_score is not None:
                log += f" -> Prédiction (t+1m): {predicted_score:.1f}%"

                # Logique de Capacity Planning
                current_pods = self.api.read_namespaced_deployment("oai-upf", self.ns).spec.replicas or 1
                ratio = predicted_score / self.target_load

                if ratio > 1.1 or ratio < 0.8:  # Seuil d'hystérésis (10-20%)
                    new_replicas = np.ceil(current_pods * ratio) if ratio > 1 else np.floor(current_pods * ratio)
                    self.scale_deployment("oai-smf", new_replicas)
                    self.scale_deployment("oai-upf", new_replicas)
            else:
                log += " [Entrainement...]"

            logger.info(log)
            time.sleep(30)


if __name__ == "__main__":
    Autoscaler().run()