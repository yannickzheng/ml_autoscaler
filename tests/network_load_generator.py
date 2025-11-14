#!/usr/bin/env python3
"""
Script de test de performance réseau pour déclencher l'autoscaling
Utilise iPerf3 et ping pour générer de la charge réseau
"""

import subprocess
import threading
import time
import random
import logging
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NetworkLoadGenerator:
    """Générateur de charge réseau pour tester l'autoscaling"""
    
    def __init__(self, namespace="nexslice"):
        self.namespace = namespace
        self.iperf_servers = []
        self.test_duration = 300  # 5 minutes par défaut
        
    def get_ue_pods(self):
        """Récupère la liste des pods UE disponibles"""
        try:
            result = subprocess.run([
                "kubectl", "get", "pods", "-n", self.namespace,
                "-l", "app=ueransim-ue", "-o", "jsonpath={.items[*].metadata.name}"
            ], capture_output=True, text=True)
            
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split()
            return []
        except Exception as e:
            logger.error(f"Erreur récupération pods UE: {e}")
            return []
    
    def deploy_iperf_server(self):
        """Déploie un serveur iPerf3 dans le cluster"""
        manifest = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: iperf3-server
  namespace: {namespace}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: iperf3-server
  template:
    metadata:
      labels:
        app: iperf3-server
    spec:
      containers:
      - name: iperf3
        image: maitaba/iperf3:latest
        ports:
        - containerPort: 5201
        command: ["iperf3"]
        args: ["-s", "-p", "5201"]
---
apiVersion: v1
kind: Service
metadata:
  name: iperf3-server
  namespace: {namespace}
spec:
  selector:
    app: iperf3-server
  ports:
  - port: 5201
    targetPort: 5201
  type: ClusterIP
        """.format(namespace=self.namespace)
        
        try:
            # Applique le manifest
            process = subprocess.Popen(['kubectl', 'apply', '-f', '-'], 
                                     stdin=subprocess.PIPE, 
                                     stdout=subprocess.PIPE, 
                                     stderr=subprocess.PIPE, 
                                     text=True)
            stdout, stderr = process.communicate(input=manifest)
            
            if process.returncode == 0:
                logger.info("Serveur iPerf3 déployé avec succès")
                time.sleep(10)  # Attend que le pod soit prêt
                return True
            else:
                logger.error(f"Erreur déploiement serveur iPerf3: {stderr}")
                return False
        except Exception as e:
            logger.error(f"Erreur déploiement serveur: {e}")
            return False
    
    def run_iperf_test(self, ue_pod, server_ip="iperf3-server", duration=60):
        """Lance un test iPerf3 depuis un pod UE"""
        try:
            cmd = [
                "kubectl", "exec", "-n", self.namespace, ue_pod, "--",
                "iperf3", "-c", server_ip, "-t", str(duration), "-P", "4"
            ]
            
            logger.info(f"Démarrage test iPerf3 depuis {ue_pod}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration+10)
            
            if result.returncode == 0:
                logger.info(f"Test iPerf3 terminé pour {ue_pod}")
                return result.stdout
            else:
                logger.error(f"Erreur test iPerf3 {ue_pod}: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout test iPerf3 pour {ue_pod}")
            return None
        except Exception as e:
            logger.error(f"Erreur test iPerf3 {ue_pod}: {e}")
            return None
    
    def run_ping_test(self, ue_pod, target="8.8.8.8", count=100):
        """Lance un test ping depuis un pod UE"""
        try:
            cmd = [
                "kubectl", "exec", "-n", self.namespace, ue_pod, "--",
                "ping", "-c", str(count), "-i", "0.1", target
            ]
            
            logger.info(f"Démarrage test ping depuis {ue_pod}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=count*2)
            
            if result.returncode == 0:
                logger.info(f"Test ping terminé pour {ue_pod}")
                return result.stdout
            else:
                logger.error(f"Erreur test ping {ue_pod}: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout test ping pour {ue_pod}")
            return None
        except Exception as e:
            logger.error(f"Erreur test ping {ue_pod}: {e}")
            return None
    
    def generate_gradual_load(self, max_concurrent_tests=10):
        """Génère une charge graduellement croissante"""
        logger.info("Démarrage génération de charge graduée")
        
        ue_pods = self.get_ue_pods()
        if not ue_pods:
            logger.error("Aucun pod UE trouvé")
            return
        
        # Déploie le serveur iPerf3
        if not self.deploy_iperf_server():
            logger.error("Impossible de déployer le serveur iPerf3")
            return
        
        # Phase 1: Charge légère (ping seulement)
        logger.info("Phase 1: Charge légère - tests ping")
        with ThreadPoolExecutor(max_workers=min(3, len(ue_pods))) as executor:
            futures = []
            for i, ue_pod in enumerate(ue_pods[:3]):
                future = executor.submit(self.run_ping_test, ue_pod, count=50)
                futures.append(future)
            
            for future in futures:
                future.result()
        
        time.sleep(30)
        
        # Phase 2: Charge moyenne (ping + quelques iPerf3)
        logger.info("Phase 2: Charge moyenne - ping + iPerf3")
        with ThreadPoolExecutor(max_workers=min(5, len(ue_pods))) as executor:
            futures = []
            
            # Tests ping
            for ue_pod in ue_pods[:3]:
                future = executor.submit(self.run_ping_test, ue_pod, count=100)
                futures.append(future)
            
            # Tests iPerf3
            for ue_pod in ue_pods[3:5]:
                future = executor.submit(self.run_iperf_test, ue_pod, duration=60)
                futures.append(future)
            
            for future in futures:
                future.result()
        
        time.sleep(30)
        
        # Phase 3: Charge élevée (tous les tests)
        logger.info("Phase 3: Charge élevée - tests intensifs")
        with ThreadPoolExecutor(max_workers=max_concurrent_tests) as executor:
            futures = []
            
            for ue_pod in ue_pods[:max_concurrent_tests]:
                # Alterne entre ping et iPerf3
                if random.choice([True, False]):
                    future = executor.submit(self.run_iperf_test, ue_pod, duration=120)
                else:
                    future = executor.submit(self.run_ping_test, ue_pod, count=200)
                futures.append(future)
            
            for future in futures:
                future.result()
        
        logger.info("Génération de charge terminée")
    
    def cleanup(self):
        """Nettoie les ressources de test"""
        try:
            subprocess.run([
                "kubectl", "delete", "deployment,service", 
                "-n", self.namespace, "-l", "app=iperf3-server"
            ], capture_output=True)
            logger.info("Nettoyage des ressources de test terminé")
        except Exception as e:
            logger.error(f"Erreur nettoyage: {e}")

def main():
    """Fonction principale"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Générateur de charge réseau pour NexSlice")
    parser.add_argument("--namespace", default="nexslice", help="Namespace Kubernetes")
    parser.add_argument("--max-tests", type=int, default=10, help="Nombre max de tests concurrents")
    parser.add_argument("--cleanup", action="store_true", help="Nettoie seulement les ressources")
    
    args = parser.parse_args()
    
    generator = NetworkLoadGenerator(namespace=args.namespace)
    
    if args.cleanup:
        generator.cleanup()
    else:
        try:
            generator.generate_gradual_load(max_concurrent_tests=args.max_tests)
        finally:
            generator.cleanup()

if __name__ == "__main__":
    main()
