#!/usr/bin/env python3
"""
ML-based Autoscaler pour VNFs SMF/UPF dans NexSlice
Utilise des métriques réseau (ping, iPerf3) et ML pour prédire la charge
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from prometheus_api_client import PrometheusConnect
from kubernetes import client, config
import time
import logging
import json
from datetime import datetime, timedelta
import subprocess
import threading

# Configuration logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NetworkMetricsCollector:
    """Collecte les métriques réseau (ping, iPerf3)"""
    
    def __init__(self, prometheus_url="http://localhost:9090"):
        self.prom = PrometheusConnect(url=prometheus_url, disable_ssl=True)
        
    def get_ping_metrics(self):
        """Récupère les métriques de latence ping"""
        try:
            # Requête Prometheus pour les métriques de ping
            ping_query = 'probe_duration_seconds{job="blackbox"}'
            ping_data = self.prom.custom_query(query=ping_query)
            
            if ping_data:
                return float(ping_data[0]['value'][1]) * 1000  # Convert to ms
            return 0.0
        except Exception as e:
            logger.error(f"Erreur collecte ping: {e}")
            return 0.0
    
    def get_iperf3_metrics(self):
        """Récupère les métriques de débit iPerf3"""
        try:
            # Métriques de throughput réseau
            throughput_query = 'rate(container_network_transmit_bytes_total[5m])'
            throughput_data = self.prom.custom_query(query=throughput_query)
            
            total_throughput = 0.0
            for metric in throughput_data:
                if 'smf' in metric['metric'].get('pod', '') or 'upf' in metric['metric'].get('pod', ''):
                    total_throughput += float(metric['value'][1])
            
            return total_throughput / (1024 * 1024)  # Convert to MB/s
        except Exception as e:
            logger.error(f"Erreur collecte iPerf3: {e}")
            return 0.0
    
    def get_pod_metrics(self):
        """Récupère les métriques CPU/Mémoire des pods SMF/UPF"""
        try:
            cpu_query = 'rate(container_cpu_usage_seconds_total{pod=~".*smf.*|.*upf.*"}[5m]) * 100'
            memory_query = 'container_memory_usage_bytes{pod=~".*smf.*|.*upf.*"} / container_spec_memory_limit_bytes * 100'
            
            cpu_data = self.prom.custom_query(query=cpu_query)
            memory_data = self.prom.custom_query(query=memory_query)
            
            avg_cpu = np.mean([float(d['value'][1]) for d in cpu_data]) if cpu_data else 0.0
            avg_memory = np.mean([float(d['value'][1]) for d in memory_data]) if memory_data else 0.0
            
            return avg_cpu, avg_memory
        except Exception as e:
            logger.error(f"Erreur collecte métriques pods: {e}")
            return 0.0, 0.0

class MLPredictor:
    """Modèle ML pour prédire la charge future"""
    
    def __init__(self, model_type='linear'):
        self.model_type = model_type
        self.model = LinearRegression() if model_type == 'linear' else RandomForestRegressor(n_estimators=100)
        self.features_history = []
        self.target_history = []
        self.is_trained = False
        
    def add_data_point(self, features, target):
        """Ajoute un point de données pour l'entraînement"""
        self.features_history.append(features)
        self.target_history.append(target)
        
        # Garde seulement les 100 derniers points
        if len(self.features_history) > 100:
            self.features_history.pop(0)
            self.target_history.pop(0)
    
    def train_model(self):
        """Entraîne le modèle avec les données historiques"""
        if len(self.features_history) < 10:
            logger.info("Pas assez de données pour l'entraînement")
            return False
            
        try:
            X = np.array(self.features_history)
            y = np.array(self.target_history)
            
            self.model.fit(X, y)
            self.is_trained = True
            logger.info("Modèle ML entraîné avec succès")
            return True
        except Exception as e:
            logger.error(f"Erreur entraînement modèle: {e}")
            return False
    
    def predict_load(self, current_features):
        """Prédit la charge future"""
        if not self.is_trained:
            return current_features[-1]  # Retourne la charge actuelle si pas de modèle
            
        try:
            prediction = self.model.predict([current_features])[0]
            return max(0, prediction)  # Assure une prédiction positive
        except Exception as e:
            logger.error(f"Erreur prédiction: {e}")
            return current_features[-1]

class VNFAutoscaler:
    """Autoscaler principal pour les VNFs SMF/UPF"""
    
    def __init__(self, namespace="nexslice"):
        self.namespace = namespace
        self.metrics_collector = NetworkMetricsCollector()
        self.predictor = MLPredictor()
        
        # Configuration Kubernetes
        try:
            config.load_incluster_config()  # Pour exécution dans le cluster
        except:
            config.load_kube_config()  # Pour développement local
            
        self.apps_v1 = client.AppsV1Api()
        self.custom_api = client.CustomObjectsApi()
        
        # Seuils de scaling
        self.cpu_threshold = 70.0
        self.memory_threshold = 80.0
        self.latency_threshold = 100.0  # ms
        self.throughput_threshold = 50.0  # MB/s
        
        # Limites de pods
        self.min_replicas = 2
        self.max_replicas = 10
        
    def get_current_replicas(self, deployment_name):
        """Récupère le nombre actuel de répliques"""
        try:
            deployment = self.apps_v1.read_namespaced_deployment(
                name=deployment_name, namespace=self.namespace
            )
            return deployment.spec.replicas
        except Exception as e:
            logger.error(f"Erreur lecture deployment {deployment_name}: {e}")
            return self.min_replicas
    
    def scale_deployment(self, deployment_name, new_replicas):
        """Scale un deployment"""
        try:
            # Patch du deployment
            body = {'spec': {'replicas': new_replicas}}
            self.apps_v1.patch_namespaced_deployment(
                name=deployment_name,
                namespace=self.namespace,
                body=body
            )
            logger.info(f"Deployment {deployment_name} scalé à {new_replicas} répliques")
            return True
        except Exception as e:
            logger.error(f"Erreur scaling {deployment_name}: {e}")
            return False
    
    def calculate_desired_replicas(self, current_replicas, predicted_load):
        """Calcule le nombre désiré de répliques basé sur la prédiction ML"""
        
        # Facteur de scaling basé sur la charge prédite
        if predicted_load > 80:
            scale_factor = 1.5
        elif predicted_load > 60:
            scale_factor = 1.2
        elif predicted_load < 30:
            scale_factor = 0.8
        else:
            scale_factor = 1.0
        
        desired_replicas = int(current_replicas * scale_factor)
        
        # Applique les limites
        desired_replicas = max(self.min_replicas, min(self.max_replicas, desired_replicas))
        
        return desired_replicas
    
    def run_autoscaling_loop(self):
        """Boucle principale d'autoscaling"""
        logger.info("Démarrage de l'autoscaler ML")
        
        while True:
            try:
                # Collecte des métriques
                ping_latency = self.metrics_collector.get_ping_metrics()
                throughput = self.metrics_collector.get_iperf3_metrics()
                cpu_usage, memory_usage = self.metrics_collector.get_pod_metrics()
                
                # Features pour le modèle ML
                current_features = [ping_latency, throughput, cpu_usage, memory_usage]
                
                # Calcul de la charge combinée (score composite)
                load_score = (
                    (cpu_usage / 100) * 0.3 +
                    (memory_usage / 100) * 0.3 +
                    (ping_latency / 200) * 0.2 +
                    (throughput / 100) * 0.2
                ) * 100
                
                # Ajoute le point de données pour l'apprentissage
                self.predictor.add_data_point(current_features, load_score)
                
                # Entraîne le modèle périodiquement
                if len(self.predictor.features_history) % 20 == 0:
                    self.predictor.train_model()
                
                # Prédiction de la charge future
                predicted_load = self.predictor.predict_load(current_features)
                
                # Log des métriques
                logger.info(f"Métriques - Ping: {ping_latency:.2f}ms, "
                           f"Throughput: {throughput:.2f}MB/s, "
                           f"CPU: {cpu_usage:.2f}%, Memory: {memory_usage:.2f}%")
                logger.info(f"Charge actuelle: {load_score:.2f}, Prédite: {predicted_load:.2f}")
                
                # Autoscaling pour SMF
                smf_replicas = self.get_current_replicas("oai-smf")
                desired_smf = self.calculate_desired_replicas(smf_replicas, predicted_load)
                
                if desired_smf != smf_replicas:
                    logger.info(f"Scaling SMF: {smf_replicas} -> {desired_smf}")
                    self.scale_deployment("oai-smf", desired_smf)
                
                # Autoscaling pour UPF
                upf_replicas = self.get_current_replicas("oai-upf")
                desired_upf = self.calculate_desired_replicas(upf_replicas, predicted_load)
                
                if desired_upf != upf_replicas:
                    logger.info(f"Scaling UPF: {upf_replicas} -> {desired_upf}")
                    self.scale_deployment("oai-upf", desired_upf)
                
                # Attend avant la prochaine itération
                time.sleep(30)
                
            except Exception as e:
                logger.error(f"Erreur dans la boucle d'autoscaling: {e}")
                time.sleep(10)

if __name__ == "__main__":
    autoscaler = VNFAutoscaler()
    autoscaler.run_autoscaling_loop()
