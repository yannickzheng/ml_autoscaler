#!/usr/bin/env python3
"""
Générateur de charge Réseau pour NexSlice (K3s Version)
Génère du trafic Ping et iPerf3 depuis les UEs vers un serveur.
"""

import subprocess
import time
import random
import logging
import argparse
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# Commande K3s
KUBECTL = "sudo k3s kubectl"


class NetworkLoadGenerator:
    def __init__(self, namespace="nexslice"):
        self.namespace = namespace

    def _run_cmd(self, cmd_str):
        """Helper pour exécuter des commandes shell"""
        try:
            # shell=True permet de gérer 'sudo' et les pipes facilement
            res = subprocess.run(cmd_str, shell=True, capture_output=True, text=True)
            return res.stdout.strip(), res.returncode
        except Exception as e:
            logger.error(f"Erreur cmd: {e}")
            return "", 1

    def get_ue_pods(self):
        """Récupère les pods UERANSIM"""
        # On cherche large : label 'app=ueransim-ue' ou noms contenants 'ueransim-ue'
        cmd = f"{KUBECTL} get pods -n {self.namespace} --no-headers -o custom-columns=\":metadata.name\""
        out, _ = self._run_cmd(cmd)

        # Filtre simple en python
        pods = [p for p in out.split('\n') if 'ueransim-ue' in p or 'nr-ue' in p]
        return pods

    def deploy_iperf_server(self):
        """Déploie le serveur cible"""
        logger.info("Déploiement du serveur iPerf3...")
        # On utilise kubectl run pour faire simple et rapide
        check, _ = self._run_cmd(f"{KUBECTL} get pod iperf3-server -n {self.namespace}")

        if "iperf3-server" not in check:
            self._run_cmd(f"{KUBECTL} run iperf3-server --image=networkstatic/iperf3 -n {self.namespace} -- -s")
            self._run_cmd(f"{KUBECTL} expose pod iperf3-server --port=5201 --name=iperf3-server -n {self.namespace}")
            logger.info("Attente du démarrage serveur (10s)...")
            time.sleep(10)
        else:
            logger.info("Serveur iPerf3 déjà présent.")

    def run_stress_test(self, ue_pod, duration=60):
        """Lance un stress test depuis un UE"""
        mode = random.choice(["ping", "iperf"])

        if mode == "ping":
            # Ping flood (rapide)
            cmd = f"{KUBECTL} exec -n {self.namespace} {ue_pod} -- ping -c {duration * 2} -i 0.5 8.8.8.8"
            logger.info(f"🚀 [{ue_pod}] PING Flood vers Internet...")
        else:
            # iPerf3 vers le serveur interne
            # Note: On suppose que le serveur est accessible via le service 'iperf3-server'
            cmd = f"{KUBECTL} exec -n {self.namespace} {ue_pod} -- iperf3 -c iperf3-server -t {duration} -b 10M"
            logger.info(f"🔥 [{ue_pod}] iPERF3 Load vers Core...")

        # Exécution (bloquante pour le thread)
        self._run_cmd(cmd)

    def generate_gradual_load(self, max_concurrent=5):
        ue_pods = self.get_ue_pods()
        if not ue_pods:
            logger.error("Aucun pod UE trouvé ! Déployez d'abord le RAN.")
            return

        self.deploy_iperf_server()

        logger.info(f"Début du test de charge sur {len(ue_pods)} UEs...")

        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            # On lance des tests en boucle
            start_time = time.time()
            # On tourne pendant 10 minutes max si appelé directement
            while time.time() - start_time < 600:
                futures = []
                # On choisit des UEs au hasard
                selected_ues = random.sample(ue_pods, min(len(ue_pods), max_concurrent))

                for ue in selected_ues:
                    futures.append(executor.submit(self.run_stress_test, ue, duration=45))

                # Attente que cette vague finisse
                for f in futures:
                    f.result()

                logger.info("--- Fin de la vague, pause 5s ---")
                time.sleep(5)

    def cleanup(self):
        logger.info("Nettoyage des ressources de test...")
        self._run_cmd(f"{KUBECTL} delete pod iperf3-server -n {self.namespace}")
        self._run_cmd(f"{KUBECTL} delete svc iperf3-server -n {self.namespace}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-tests", type=int, default=5)
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    gen = NetworkLoadGenerator()

    if args.cleanup:
        gen.cleanup()
    else:
        try:
            gen.generate_gradual_load(max_concurrent=args.max_tests)
        except KeyboardInterrupt:
            logger.info("Arrêt utilisateur.")