#!/usr/bin/env python3
"""
Script de benchmark pour comparer HPA Kubernetes vs Autoscaler ML
Collecte les métriques de performance et génère un rapport
"""

import time
import json
import csv
import subprocess
import threading
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from prometheus_api_client import PrometheusConnect

class AutoscalerBenchmark:
    """Benchmark pour comparer HPA vs ML Autoscaler"""
    
    def __init__(self, namespace="nexslice", prometheus_url="http://localhost:9090"):
        self.namespace = namespace
        self.prom = PrometheusConnect(url=prometheus_url, disable_ssl=True)
        self.metrics_data = []
        self.test_duration = 1800  # 30 minutes par défaut
        self.collection_interval = 30  # Collecte toutes les 30 secondes
        
    def get_pod_count(self, deployment_name):
        """Récupère le nombre de pods pour un deployment"""
        try:
            result = subprocess.run([
                "kubectl", "get", "deployment", deployment_name, "-n", self.namespace,
                "-o", "jsonpath={.status.replicas}"
            ], capture_output=True, text=True)
            
            return int(result.stdout.strip()) if result.stdout.strip() else 0
        except:
            return 0
    
    def get_resource_usage(self):
        """Collecte les métriques d'utilisation des ressources"""
        try:
            # CPU total du cluster
            cpu_query = 'sum(rate(container_cpu_usage_seconds_total{container!="POD",container!=""}[5m])) * 100'
            cpu_data = self.prom.custom_query(query=cpu_query)
            total_cpu = float(cpu_data[0]['value'][1]) if cpu_data else 0.0
            
            # Mémoire totale utilisée
            memory_query = 'sum(container_memory_usage_bytes{container!="POD",container!=""}) / 1024 / 1024 / 1024'
            memory_data = self.prom.custom_query(query=memory_query)
            total_memory = float(memory_data[0]['value'][1]) if memory_data else 0.0
            
            # Métriques spécifiques aux pods SMF/UPF
            smf_cpu_query = 'sum(rate(container_cpu_usage_seconds_total{pod=~".*smf.*"}[5m])) * 100'
            upf_cpu_query = 'sum(rate(container_cpu_usage_seconds_total{pod=~".*upf.*"}[5m])) * 100'
            
            smf_cpu_data = self.prom.custom_query(query=smf_cpu_query)
            upf_cpu_data = self.prom.custom_query(query=upf_cpu_query)
            
            smf_cpu = float(smf_cpu_data[0]['value'][1]) if smf_cpu_data else 0.0
            upf_cpu = float(upf_cpu_data[0]['value'][1]) if upf_cpu_data else 0.0
            
            return {
                'total_cpu': total_cpu,
                'total_memory': total_memory,
                'smf_cpu': smf_cpu,
                'upf_cpu': upf_cpu
            }
        except Exception as e:
            print(f"Erreur collecte métriques: {e}")
            return {}
    
    def get_network_metrics(self):
        """Collecte les métriques réseau"""
        try:
            # Latence réseau
            latency_query = 'probe_duration_seconds{job="blackbox"}'
            latency_data = self.prom.custom_query(query=latency_query)
            latency = float(latency_data[0]['value'][1]) * 1000 if latency_data else 0.0
            
            # Throughput réseau
            throughput_query = 'sum(rate(container_network_transmit_bytes_total[5m]))'
            throughput_data = self.prom.custom_query(query=throughput_query)
            throughput = float(throughput_data[0]['value'][1]) / 1024 / 1024 if throughput_data else 0.0
            
            return {
                'latency_ms': latency,
                'throughput_mbps': throughput
            }
        except Exception as e:
            print(f"Erreur métriques réseau: {e}")
            return {}
    
    def get_5g_specific_metrics(self):
        """Collecte les métriques spécifiques à la 5G"""
        try:
            # Nombre de sessions UE actives
            ue_sessions_query = 'count(kube_pod_info{namespace="nexslice", pod=~".*ue.*"})'
            ue_data = self.prom.custom_query(query=ue_sessions_query)
            active_ues = float(ue_data[0]['value'][1]) if ue_data else 0.0
            
            # Métriques AMF (Access and Mobility Management Function)
            amf_cpu_query = 'rate(container_cpu_usage_seconds_total{pod=~".*amf.*"}[5m]) * 100'
            amf_data = self.prom.custom_query(query=amf_cpu_query)
            amf_cpu = float(amf_data[0]['value'][1]) if amf_data else 0.0
            
            # Throughput par slice (SST-based)
            slice_throughput_query = 'sum(rate(container_network_receive_bytes_total{namespace="nexslice"}[5m])) by (pod)'
            slice_data = self.prom.custom_query(query=slice_throughput_query)
            total_slice_throughput = sum(float(d['value'][1]) for d in slice_data) / 1024 / 1024
            
            # Latence de handover (si disponible)
            handover_latency_query = 'histogram_quantile(0.95, rate(handover_duration_seconds_bucket[5m]))'
            handover_data = self.prom.custom_query(query=handover_latency_query)
            handover_latency = float(handover_data[0]['value'][1]) * 1000 if handover_data else 0.0
            
            return {
                'active_ues': active_ues,
                'amf_cpu': amf_cpu,
                'slice_throughput_mbps': total_slice_throughput,
                'handover_latency_ms': handover_latency
            }
        except Exception as e:
            print(f"Erreur métriques 5G: {e}")
            return {}

    def get_vnf_scaling_efficiency(self):
        """Calcule l'efficacité du scaling des VNFs"""
        try:
            # Ratio CPU utilisé vs CPU alloué
            cpu_efficiency_query = '''
            avg(rate(container_cpu_usage_seconds_total{pod=~".*smf.*|.*upf.*"}[5m])) /
            avg(container_spec_cpu_quota{pod=~".*smf.*|.*upf.*"} / container_spec_cpu_period{pod=~".*smf.*|.*upf.*"})
            '''
            cpu_eff_data = self.prom.custom_query(query=cpu_efficiency_query)
            cpu_efficiency = float(cpu_eff_data[0]['value'][1]) if cpu_eff_data else 0.0
            
            # Ratio mémoire utilisée vs mémoire allouée
            memory_efficiency_query = '''
            avg(container_memory_usage_bytes{pod=~".*smf.*|.*upf.*"}) /
            avg(container_spec_memory_limit_bytes{pod=~".*smf.*|.*upf.*"})
            '''
            mem_eff_data = self.prom.custom_query(query=memory_efficiency_query)
            memory_efficiency = float(mem_eff_data[0]['value'][1]) if mem_eff_data else 0.0
            
            return {
                'cpu_efficiency': cpu_efficiency * 100,
                'memory_efficiency': memory_efficiency * 100
            }
        except Exception as e:
            print(f"Erreur efficacité VNF: {e}")
            return {'cpu_efficiency': 0.0, 'memory_efficiency': 0.0}

    def collect_metrics(self):
        """Collecte toutes les métriques à un instant donné"""
        timestamp = datetime.now()
        
        # Nombre de pods
        smf_pods = self.get_pod_count("oai-smf")
        upf_pods = self.get_pod_count("oai-upf")
        
        # Utilisation des ressources
        resource_usage = self.get_resource_usage()
        
        # Métriques réseau
        network_metrics = self.get_network_metrics()
        
        # Métriques 5G spécifiques
        fiveG_metrics = self.get_5g_specific_metrics()
        
        # Efficacité du scaling
        scaling_efficiency = self.get_vnf_scaling_efficiency()
        
        # Compile toutes les métriques
        metrics = {
            'timestamp': timestamp.isoformat(),
            'smf_pods': smf_pods,
            'upf_pods': upf_pods,
            **resource_usage,
            **network_metrics,
            **fiveG_metrics,
            **scaling_efficiency
        }
        
        return metrics
    
    def enable_hpa(self):
        """Active le HPA Kubernetes"""
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
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
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
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
        """
        
        try:
            process = subprocess.Popen(['kubectl', 'apply', '-f', '-'], 
                                     stdin=subprocess.PIPE, 
                                     stdout=subprocess.PIPE, 
                                     stderr=subprocess.PIPE, 
                                     text=True)
            stdout, stderr = process.communicate(input=hpa_manifest)
            
            if process.returncode == 0:
                print("HPA activé avec succès")
                return True
            else:
                print(f"Erreur activation HPA: {stderr}")
                return False
        except Exception as e:
            print(f"Erreur HPA: {e}")
            return False
    
    def disable_hpa(self):
        """Désactive le HPA"""
        try:
            subprocess.run([
                "kubectl", "delete", "hpa", 
                "oai-smf-hpa", "oai-upf-hpa", 
                "-n", self.namespace, "--ignore-not-found=true"
            ], capture_output=True)
            print("HPA désactivé")
        except Exception as e:
            print(f"Erreur désactivation HPA: {e}")
    
    def start_ml_autoscaler(self):
        """Démarre l'autoscaler ML en arrière-plan"""
        try:
            # Lance le script ML autoscaler
            self.ml_process = subprocess.Popen([
                "python3", "/Users/as/Documents/Projets/ml-autoscaler/autoscaling/ml_autoscaler.py"
            ])
            time.sleep(10)  # Temps pour démarrer
            print("Autoscaler ML démarré")
            return True
        except Exception as e:
            print(f"Erreur démarrage ML autoscaler: {e}")
            return False
    
    def stop_ml_autoscaler(self):
        """Arrête l'autoscaler ML"""
        try:
            if hasattr(self, 'ml_process'):
                self.ml_process.terminate()
                self.ml_process.wait()
            print("Autoscaler ML arrêté")
        except Exception as e:
            print(f"Erreur arrêt ML autoscaler: {e}")
    
    def run_benchmark_phase(self, phase_name, autoscaler_type, duration_minutes=15):
        """Lance une phase de benchmark"""
        print(f"Démarrage phase: {phase_name} avec {autoscaler_type}")
        
        phase_data = []
        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)
        
        while time.time() < end_time:
            metrics = self.collect_metrics()
            metrics['phase'] = phase_name
            metrics['autoscaler_type'] = autoscaler_type
            
            phase_data.append(metrics)
            print(f"[{phase_name}] SMF: {metrics['smf_pods']}, UPF: {metrics['upf_pods']}, "
                  f"CPU: {metrics.get('total_cpu', 0):.2f}%")
            
            time.sleep(self.collection_interval)
        
        return phase_data
    
    def generate_load_during_test(self):
        """Génère de la charge pendant le test"""
        from .network_load_generator import NetworkLoadGenerator
        
        generator = NetworkLoadGenerator(namespace=self.namespace)
        try:
            generator.generate_gradual_load(max_concurrent_tests=8)
        except Exception as e:
            print(f"Erreur génération de charge: {e}")
    
    def run_full_benchmark(self):
        """Lance le benchmark complet"""
        print("Démarrage du benchmark complet HPA vs ML Autoscaler")
        
        all_data = []
        
        # Phase 1: Test avec HPA
        print("\n=== PHASE 1: Test avec HPA Kubernetes ===")
        self.disable_hpa()  # Reset
        self.enable_hpa()
        
        # Génère la charge en parallèle
        load_thread = threading.Thread(target=self.generate_load_during_test)
        load_thread.daemon = True
        load_thread.start()
        
        hpa_data = self.run_benchmark_phase("HPA_Test", "HPA", duration_minutes=15)
        all_data.extend(hpa_data)
        
        # Période de refroidissement
        print("\n=== Période de refroidissement ===")
        self.disable_hpa()
        time.sleep(300)  # 5 minutes
        
        # Phase 2: Test avec ML Autoscaler
        print("\n=== PHASE 2: Test avec ML Autoscaler ===")
        self.start_ml_autoscaler()
        
        # Nouvelle charge
        load_thread = threading.Thread(target=self.generate_load_during_test)
        load_thread.daemon = True
        load_thread.start()
        
        ml_data = self.run_benchmark_phase("ML_Test", "ML", duration_minutes=15)
        all_data.extend(ml_data)
        
        self.stop_ml_autoscaler()
        
        # Sauvegarde les données
        self.save_benchmark_data(all_data)
        
        # Génère le rapport
        self.generate_report(all_data)
        
        return all_data
    
    def save_benchmark_data(self, data):
        """Sauvegarde les données de benchmark"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Sauvegarde JSON
        json_filename = f"benchmark_data_{timestamp}.json"
        with open(json_filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Sauvegarde CSV
        csv_filename = f"benchmark_data_{timestamp}.csv"
        df = pd.DataFrame(data)
        df.to_csv(csv_filename, index=False)
        
        print(f"Données sauvegardées: {json_filename}, {csv_filename}")
    
    def generate_report(self, data):
        """Génère un rapport de comparaison"""
        df = pd.DataFrame(data)
        
        # Sépare les données par type d'autoscaler
        hpa_data = df[df['autoscaler_type'] == 'HPA']
        ml_data = df[df['autoscaler_type'] == 'ML']
        
        # Calculs statistiques
        print("\n=== RAPPORT DE COMPARAISON ===")
        print("\nHPA Kubernetes:")
        print(f"  SMF pods - Moyenne: {hpa_data['smf_pods'].mean():.2f}, Max: {hpa_data['smf_pods'].max()}")
        print(f"  UPF pods - Moyenne: {hpa_data['upf_pods'].mean():.2f}, Max: {hpa_data['upf_pods'].max()}")
        print(f"  CPU moyen: {hpa_data['total_cpu'].mean():.2f}%")
        
        print("\nML Autoscaler:")
        print(f"  SMF pods - Moyenne: {ml_data['smf_pods'].mean():.2f}, Max: {ml_data['smf_pods'].max()}")
        print(f"  UPF pods - Moyenne: {ml_data['upf_pods'].mean():.2f}, Max: {ml_data['upf_pods'].max()}")
        print(f"  CPU moyen: {ml_data['total_cpu'].mean():.2f}%")
        
        # Calcul d'efficacité
        hpa_efficiency = hpa_data['total_cpu'].mean() / (hpa_data['smf_pods'].mean() + hpa_data['upf_pods'].mean())
        ml_efficiency = ml_data['total_cpu'].mean() / (ml_data['smf_pods'].mean() + ml_data['upf_pods'].mean())
        
        print(f"\nEfficacité (CPU/Pod):")
        print(f"  HPA: {hpa_efficiency:.2f}")
        print(f"  ML:  {ml_efficiency:.2f}")
        print(f"  Amélioration: {((ml_efficiency - hpa_efficiency) / hpa_efficiency * 100):+.1f}%")
        
        # Graphiques
        self.create_comparison_plots(df)
    
    def create_comparison_plots(self, df):
        """Crée des graphiques de comparaison"""
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        
        # Convertit timestamp en datetime
        df['datetime'] = pd.to_datetime(df['timestamp'])
        
        # Plot 1: Nombre de pods SMF
        for autoscaler in ['HPA', 'ML']:
            data = df[df['autoscaler_type'] == autoscaler]
            axes[0, 0].plot(data['datetime'], data['smf_pods'], 
                          label=f'SMF - {autoscaler}', marker='o')
        axes[0, 0].set_title('Nombre de pods SMF')
        axes[0, 0].set_ylabel('Pods')
        axes[0, 0].legend()
        axes[0, 0].grid(True)
        
        # Plot 2: Nombre de pods UPF
        for autoscaler in ['HPA', 'ML']:
            data = df[df['autoscaler_type'] == autoscaler]
            axes[0, 1].plot(data['datetime'], data['upf_pods'], 
                          label=f'UPF - {autoscaler}', marker='s')
        axes[0, 1].set_title('Nombre de pods UPF')
        axes[0, 1].set_ylabel('Pods')
        axes[0, 1].legend()
        axes[0, 1].grid(True)
        
        # Plot 3: Utilisation CPU
        for autoscaler in ['HPA', 'ML']:
            data = df[df['autoscaler_type'] == autoscaler]
            axes[1, 0].plot(data['datetime'], data['total_cpu'], 
                          label=f'CPU - {autoscaler}', marker='^')
        axes[1, 0].set_title('Utilisation CPU totale')
        axes[1, 0].set_ylabel('CPU %')
        axes[1, 0].legend()
        axes[1, 0].grid(True)
        
        # Plot 4: Latence réseau
        for autoscaler in ['HPA', 'ML']:
            data = df[df['autoscaler_type'] == autoscaler]
            if 'latency_ms' in data.columns:
                axes[1, 1].plot(data['datetime'], data['latency_ms'], 
                              label=f'Latence - {autoscaler}', marker='d')
        axes[1, 1].set_title('Latence réseau')
        axes[1, 1].set_ylabel('Latence (ms)')
        axes[1, 1].legend()
        axes[1, 1].grid(True)
        
        plt.tight_layout()
        plt.savefig(f'benchmark_comparison_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png', 
                   dpi=300, bbox_inches='tight')
        plt.show()
        
        print("Graphiques de comparaison sauvegardés")

def main():
    """Fonction principale"""
    benchmark = AutoscalerBenchmark()
    
    try:
        benchmark.run_full_benchmark()
    except KeyboardInterrupt:
        print("\nBenchmark interrompu par l'utilisateur")
        benchmark.disable_hpa()
        benchmark.stop_ml_autoscaler()
    except Exception as e:
        print(f"Erreur pendant le benchmark: {e}")
        benchmark.disable_hpa()
        benchmark.stop_ml_autoscaler()

if __name__ == "__main__":
    main()
