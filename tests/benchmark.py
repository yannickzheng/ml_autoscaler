#!/usr/bin/env python3
"""
Script de benchmark pour comparer HPA Kubernetes vs Autoscaler ML
Version adaptée pour K3s et le déploiement In-Cluster
"""

import time
import json
import subprocess
import threading
import os
from datetime import datetime
import matplotlib.pyplot as plt
import pandas as pd
from prometheus_api_client import PrometheusConnect

# Configuration K3s
KUBECTL_CMD = "sudo k3s kubectl"


class AutoscalerBenchmark:
    """Benchmark pour comparer HPA vs ML Autoscaler"""

    def __init__(self, namespace="nexslice", prometheus_url="http://localhost:9090"):
        self.namespace = namespace
        # Note: Assurez-vous d'avoir fait le port-forward Prometheus avant de lancer ce script
        # sudo k3s kubectl port-forward -n monitoring svc/prometheus 9090:9090
        self.prom = PrometheusConnect(url=prometheus_url, disable_ssl=True)
        self.metrics_data = []
        self.collection_interval = 30

    def _run_cmd(self, cmd_list):
        """Exécute une commande shell proprement"""
        full_cmd = f"{KUBECTL_CMD} {' '.join(cmd_list[1:])}"
        try:
            # On utilise shell=True pour gérer sudo k3s correctement
            result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
            return result.stdout.strip()
        except Exception as e:
            print(f"Erreur cmd: {e}")
            return ""

    def get_pod_count(self, deployment_name):
        """Récupère le nombre de pods via kubectl"""
        try:
            cmd = ["kubectl", "get", "deployment", deployment_name, "-n", self.namespace, "-o",
                   "jsonpath={.status.replicas}"]
            out = self._run_cmd(cmd)
            return int(out) if out and out.isdigit() else 0
        except:
            return 0

    def get_metrics(self):
        """Collecte centralisée des métriques"""
        m = {}
        try:
            # CPU Total Cluster
            data = self.prom.custom_query(
                'sum(rate(container_cpu_usage_seconds_total{container!="POD",container!=""}[5m])) * 100')
            m['total_cpu'] = float(data[0]['value'][1]) if data else 0.0

            # Pods Count (Vérification temps réel)
            m['smf_pods'] = self.get_pod_count("oai-smf")
            m['upf_pods'] = self.get_pod_count("oai-upf")

            # Latence (Network)
            data = self.prom.custom_query('probe_duration_seconds{job="blackbox"}')
            m['latency_ms'] = float(data[0]['value'][1]) * 1000 if data else 0.0

            m['timestamp'] = datetime.now().isoformat()
            return m
        except Exception as e:
            print(f"Erreur collecte Prometheus: {e} (Avez-vous lancé le port-forward ?)")
            return {'timestamp': datetime.now().isoformat(), 'error': str(e)}

    def enable_hpa(self):
        """Active le HPA Kubernetes standard"""
        print("-> Activation du HPA Standard...")
        hpa_manifest = f"""
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: oai-smf-hpa
  namespace: {self.namespace}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: oai-smf
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: oai-upf-hpa
  namespace: {self.namespace}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: oai-upf
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
        """
        # Application via un fichier temporaire pour éviter les problèmes de pipe avec sudo
        with open("/tmp/hpa_temp.yaml", "w") as f:
            f.write(hpa_manifest)

        os.system(f"{KUBECTL_CMD} apply -f /tmp/hpa_temp.yaml")
        time.sleep(5)

    def disable_hpa(self):
        print("-> Désactivation du HPA...")
        self._run_cmd(["kubectl", "delete", "hpa", "oai-smf-hpa", "oai-upf-hpa", "-n", self.namespace])

    def start_ml_autoscaler(self):
        """Active le Pod ML Autoscaler dans le cluster"""
        print("-> Démarrage du ML Autoscaler (Scale UP)...")
        # On passe le replica à 1 pour allumer l'IA
        self._run_cmd(["kubectl", "scale", "deployment", "ml-autoscaler", "--replicas=1", "-n", self.namespace])
        print("Attente de 30s pour le démarrage du Pod ML...")
        time.sleep(30)

    def stop_ml_autoscaler(self):
        """Désactive le Pod ML Autoscaler"""
        print("-> Arrêt du ML Autoscaler (Scale DOWN)...")
        self._run_cmd(["kubectl", "scale", "deployment", "ml-autoscaler", "--replicas=0", "-n", self.namespace])

    def run_phase(self, phase_name, duration_minutes=15):
        print(f"\n--- Démarrage Phase: {phase_name} ({duration_minutes} min) ---")
        end_time = time.time() + (duration_minutes * 60)
        data = []

        while time.time() < end_time:
            m = self.get_metrics()
            m['phase'] = phase_name
            data.append(m)

            print(
                f"[{phase_name}] SMF: {m.get('smf_pods')}, UPF: {m.get('upf_pods')}, Latence: {m.get('latency_ms', 0):.1f}ms")
            time.sleep(self.collection_interval)
        return data

    def generate_load_background(self):
        """Lance le générateur de charge en arrière-plan"""
        print("   [Load] Démarrage du générateur de trafic...")
        # On suppose que le script est dans le même dossier
        script_dir = os.path.dirname(os.path.abspath(__file__))
        load_script = os.path.join(script_dir, "network_load_generator.py")

        # Lancement en arrière-plan
        subprocess.Popen(f"python3 {load_script} --max-tests 8", shell=True)

    def run_full_benchmark(self):
        all_data = []

        # 0. S'assurer que tout est propre au début
        self.disable_hpa()
        self.stop_ml_autoscaler()

        # --- PHASE 1 : HPA Standard ---
        print("\n=== PHASE 1 : TEST HPA STANDARD ===")
        self.enable_hpa()
        self.generate_load_background()

        data_hpa = self.run_phase("HPA", duration_minutes=10)  # 10 min pour aller plus vite
        all_data.extend(data_hpa)

        # Cooling Down
        print("\n=== REFROIDISSEMENT (5 min) ===")
        self.disable_hpa()
        # On arrête le générateur de charge (pkill bourrin mais efficace pour le TP)
        os.system("pkill -f network_load_generator.py")
        time.sleep(300)

        # --- PHASE 2 : ML Autoscaler ---
        print("\n=== PHASE 2 : TEST ML AUTOSCALER ===")
        self.start_ml_autoscaler()
        self.generate_load_background()

        data_ml = self.run_phase("ML", duration_minutes=10)
        all_data.extend(data_ml)

        self.stop_ml_autoscaler()
        os.system("pkill -f network_load_generator.py")

        # Rapport
        self.save_and_plot(all_data)

    def save_and_plot(self, data):
        df = pd.DataFrame(data)
        timestamp = datetime.now().strftime("%H%M")
        df.to_csv(f"benchmark_{timestamp}.csv", index=False)
        print(f"\nDonnées sauvegardées dans benchmark_{timestamp}.csv")

        # Simple Plot
        try:
            plt.figure(figsize=(12, 6))

            # Séparation des données
            hpa = df[df['phase'] == 'HPA']
            ml = df[df['phase'] == 'ML']

            plt.subplot(1, 2, 1)
            plt.plot(hpa['latency_ms'].values, label='HPA Latency')
            plt.plot(ml['latency_ms'].values, label='ML Latency')
            plt.title("Latence Réseau")
            plt.legend()

            plt.subplot(1, 2, 2)
            plt.plot(hpa['upf_pods'].values, label='HPA UPF Pods')
            plt.plot(ml['upf_pods'].values, label='ML UPF Pods')
            plt.title("Nombre de Pods UPF")
            plt.legend()

            plt.savefig(f"benchmark_result_{timestamp}.png")
            print(f"Graphique généré: benchmark_result_{timestamp}.png")
        except Exception as e:
            print(f"Erreur graphique: {e}")


if __name__ == "__main__":
    # Vérification Port-Forward
    print("⚠️  AVANT DE LANCER : Assurez-vous d'avoir fait le port-forward Prometheus !")
    print("   sudo k3s kubectl port-forward -n monitoring svc/prometheus 9090:9090")
    print("   (Laissez tourner cette commande dans un autre terminal)\n")
    time.sleep(3)

    AutoscalerBenchmark().run_full_benchmark()