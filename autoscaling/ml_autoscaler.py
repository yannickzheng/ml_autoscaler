#!/usr/bin/env python3
"""
ML-based Autoscaler pour NexSlice (Version Corrigée)
Approche: Time-Series Forecasting avec Random Forest
"""

import time
import logging
import os
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
WINDOW_SIZE = 5
PREDICTION_HORIZON = 2
MIN_TRAINING_DATA = 20
MAX_HISTORY = 1000


class MetricsCollector:
    def __init__(self, url=None):
        # Utilisation de la variable d'env ou valeur par défaut avec DNS complet
        if not url:
            url = os.getenv("PROMETHEUS_URL", "http://prometheus-server.monitoring.svc.cluster.local:9090")
        logger.info(f"Connexion Prometheus: {url}")
        self.prom = PrometheusConnect(url=url, disable_ssl=True)

    def get_current_metrics(self):
        m = {'cpu': 0.0, 'memory': 0.0, 'latency': 0.0, 'throughput': 0.0}
        try:
            # Latence: Correction du job name pour correspondre au YAML monitoring
            data = self.prom.custom_query('probe_duration_seconds{job="blackbox"}')
            if data: m['latency'] = float(data[0]['value'][1]) * 1000

            data = self.prom.custom_query('sum(rate(container_network_transmit_bytes_total{namespace="nexslice"}[5m]))')
            if data: m['throughput'] = float(data[0]['value'][1]) / (1024 * 1024)

            data = self.prom.custom_query(
                'avg(rate(container_cpu_usage_seconds_total{pod=~".*smf.*|.*upf.*"}[5m])) * 100')
            if data: m['cpu'] = float(data[0]['value'][1])

            data = self.prom.custom_query(
                'avg(container_memory_usage_bytes{pod=~".*smf.*|.*upf.*"} / container_spec_memory_limit_bytes) * 100')
            if data: m['memory'] = float(data[0]['value'][1])

            return m
        except Exception as e:
            logger.error(f"Erreur métriques: {e}")
            return m


class TimeSeriesPredictor:
    def __init__(self):
        self.model = RandomForestRegressor(n_estimators=50, n_jobs=-1, random_state=42)
        self.scaler = StandardScaler()
        self.history = deque(maxlen=MAX_HISTORY)
        self.is_trained = False

    def _calculate_score(self, m):
        return (0.3 * m['cpu'] +
                0.2 * m['memory'] +
                0.3 * min(100, m['latency']) +
                0.2 * min(100, m['throughput']))

    def update_and_predict(self, metrics):
        score = self._calculate_score(metrics)
        record = [metrics['cpu'], metrics['memory'], metrics['latency'], metrics['throughput'], score]
        self.history.append(record)

        if len(self.history) >= MIN_TRAINING_DATA and len(self.history) % 10 == 0:
            self._train()

        return score, self._predict_next()

    def _train(self):
        try:
            data = np.array(self.history)
            x, y = [], []
            for i in range(WINDOW_SIZE, len(data) - PREDICTION_HORIZON):
                x.append(data[i - WINDOW_SIZE:i].flatten())
                y.append(data[i + PREDICTION_HORIZON][4])

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
            current_window = np.array(self.history)[-WINDOW_SIZE:].flatten().reshape(1, -1)
            X_scaled = self.scaler.transform(current_window)
            return max(0, self.model.predict(X_scaled)[0])
        except Exception:
            return None


class Autoscaler:
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
        self.cooldown_seconds = 45

    def scale_deployment(self, name, replicas):
        """Application du scaling via API K8s sans gestion du temps ici"""
        try:
            replicas = int(max(self.min_replicas, min(self.max_replicas, replicas)))
            current = self.api.read_namespaced_deployment(name, self.ns).spec.replicas

            if replicas != current:
                logger.info(f"⚖️ SCALING {name}: {current} -> {replicas}")
                self.api.patch_namespaced_deployment(name, self.ns, {'spec': {'replicas': replicas}})
                return True  # Indique qu'un changement a eu lieu
            return False
        except Exception as e:
            logger.error(f"Erreur scaling {name}: {e}")
            return False

    def run(self):
        logger.info("Démarrage Autoscaler ML (Mode Production)")
        while True:
            m = self.collector.get_current_metrics()
            current_score, predicted_score = self.predictor.update_and_predict(m)

            log = f"Load: {current_score:.1f}% | Lat: {m['latency']:.0f}ms | CPU: {m['cpu']:.0f}%"

            if predicted_score is not None:
                log += f" -> Prédiction (t+1m): {predicted_score:.1f}%"

                # Vérification du Cooldown
                time_since_last_scale = (datetime.now() - self.last_scale).total_seconds()

                if time_since_last_scale > self.cooldown_seconds:
                    current_pods = 1
                    try:
                        # On se base sur l'UPF pour la capacité actuelle
                        current_pods = self.api.read_namespaced_deployment("oai-upf", self.ns).spec.replicas or 1
                    except:
                        pass

                    ratio = predicted_score / self.target_load

                    # Scaling
                    if ratio > 1.1 or ratio < 0.8:
                        new_replicas = np.ceil(current_pods * ratio) if ratio > 1 else np.floor(current_pods * ratio)

                        # On applique aux deux composants
                        scaled_smf = self.scale_deployment("oai-smf", new_replicas)
                        scaled_upf = self.scale_deployment("oai-upf", new_replicas)

                        # Si au moins l'un a changé, on reset le timer
                        if scaled_smf or scaled_upf:
                            self.last_scale = datetime.now()
                else:
                    log += f" [Cooldown: {int(self.cooldown_seconds - time_since_last_scale)}s]"
            else:
                log += " [Entrainement...]"

            logger.info(log)
            time.sleep(30)


if __name__ == "__main__":
    Autoscaler().run()