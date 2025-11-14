#!/bin/bash
# Installation et intégration ML Autoscaler avec NexSlice (K3s)
set -e

echo "=== Installation ML Autoscaler pour NexSlice (K3s) ==="

# Configuration
NEXSLICE_NAMESPACE="nexslice"
MONITORING_NAMESPACE="monitoring"

# Couleurs pour l'affichage
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

print_status() {
    local status=$1
    local message=$2
    case $status in
        "OK") echo -e "${GREEN}✓${NC} $message" ;;
        "WARN") echo -e "${YELLOW}⚠${NC} $message" ;;
        "ERROR") echo -e "${RED}✗${NC} $message" ;;
    esac
}

# Fonctions utilitaires pour K3s
check_k3s() {
    if command -v k3s &> /dev/null; then
        echo "Utilisation de K3s"
        KUBECTL_CMD="sudo k3s kubectl"
    elif command -v kubectl &> /dev/null; then
        echo "Utilisation de kubectl standard"
        KUBECTL_CMD="kubectl"
    else
        print_status "ERROR" "Ni K3s ni kubectl ne sont installés"
        exit 1
    fi
}

check_namespace() {
    local ns=$1
    if ! $KUBECTL_CMD get namespace "$ns" &> /dev/null; then
        echo "Création du namespace $ns..."
        $KUBECTL_CMD create namespace "$ns"
        print_status "OK" "Namespace $ns créé"
    else
        print_status "OK" "Namespace $ns existe déjà"
    fi
}

# Vérifications préalables
echo "Vérification des prérequis..."
check_k3s

# Vérification de la connectivité au cluster
if ! $KUBECTL_CMD cluster-info &> /dev/null; then
    print_status "ERROR" "Impossible de se connecter au cluster K3s"
    echo "Vérifiez que K3s est démarré et que vous avez les bonnes permissions"
    exit 1
fi

print_status "OK" "Connexion au cluster K3s établie"

# Vérification que NexSlice est déployé
if ! $KUBECTL_CMD get namespace "$NEXSLICE_NAMESPACE" &> /dev/null; then
    print_status "ERROR" "NexSlice n'est pas déployé (namespace '$NEXSLICE_NAMESPACE' introuvable)"
    echo "Veuillez d'abord déployer NexSlice selon la documentation officielle"
    exit 1
fi

# Vérification des composants NexSlice Core
core_components=("oai-amf" "oai-smf" "oai-upf")
missing_components=()

for component in "${core_components[@]}"; do
    if ! $KUBECTL_CMD get deployment "$component" -n "$NEXSLICE_NAMESPACE" &> /dev/null; then
        missing_components+=("$component")
    fi
done

if [ ${#missing_components[@]} -gt 0 ]; then
    print_status "WARN" "Composants NexSlice manquants: ${missing_components[*]}"
    echo "L'autoscaler ML nécessite que SMF et UPF soient déployés"
    read -p "Continuer malgré tout ? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

print_status "OK" "Composants NexSlice détectés"

# Création des namespaces
check_namespace "$NEXSLICE_NAMESPACE"
check_namespace "$MONITORING_NAMESPACE"

# Installation des dépendances Python (si disponible)
echo "Installation des dépendances Python..."
if command -v pip3 &> /dev/null; then
    pip3 install --user -r requirements.txt
    print_status "OK" "Dépendances Python installées"
else
    print_status "WARN" "pip3 non trouvé, installation manuelle requise"
fi

# Déploiement de la configuration de monitoring étendue
echo "Déploiement de la configuration de monitoring pour NexSlice..."
$KUBECTL_CMD apply -f kubernetes/nexslice-monitoring/nexslice-monitoring.yaml
print_status "OK" "Configuration monitoring déployée"

# Création du ConfigMap avec le code ML autoscaler
echo "Création du ConfigMap pour ML Autoscaler..."
$KUBECTL_CMD create configmap ml-autoscaler-code \
    --from-file=autoscaling/ml_autoscaler.py \
    -n "$NEXSLICE_NAMESPACE" \
    --dry-run=client -o yaml | $KUBECTL_CMD apply -f -
print_status "OK" "ConfigMap créé"

# Mise à jour du déploiement pour K3s (ajustement des ressources)
sed -i.bak 's/python:3.9-slim/python:3.9-slim/g' kubernetes/ml-autoscaler-deployment.yml
sed -i.bak 's/memory: "512Mi"/memory: "256Mi"/g' kubernetes/ml-autoscaler-deployment.yml
sed -i.bak 's/cpu: "500m"/cpu: "250m"/g' kubernetes/ml-autoscaler-deployment.yml

# Déploiement du ML Autoscaler
echo "Déploiement du ML Autoscaler..."
$KUBECTL_CMD apply -f kubernetes/ml-autoscaler-deployment.yml
print_status "OK" "ML Autoscaler déployé"

# Attendre que les pods soient prêts
echo "Attente du démarrage des composants..."

# Attente pour blackbox-exporter
if $KUBECTL_CMD wait --for=condition=ready pod -l app=blackbox-exporter -n "$MONITORING_NAMESPACE" --timeout=60s &> /dev/null; then
    print_status "OK" "Blackbox exporter démarré"
else
    print_status "WARN" "Blackbox exporter prend du temps à démarrer"
fi

# Attente pour ml-autoscaler
if $KUBECTL_CMD wait --for=condition=ready pod -l app=ml-autoscaler -n "$NEXSLICE_NAMESPACE" --timeout=120s &> /dev/null; then
    print_status "OK" "ML Autoscaler démarré"
else
    print_status "WARN" "ML Autoscaler prend du temps à démarrer"
fi

# Vérification de l'état final
echo ""
echo "=== Vérification de l'installation ==="
echo "Pods ML Autoscaler:"
$KUBECTL_CMD get pods -n "$NEXSLICE_NAMESPACE" -l app=ml-autoscaler

echo ""
echo "Pods de monitoring:"
$KUBECTL_CMD get pods -n "$MONITORING_NAMESPACE" -l app=blackbox-exporter

# Instructions pour les tests
echo ""
echo "=== Installation terminée avec succès! ==="
echo ""
echo "Commandes K3s pour tester le système:"
echo "1. Générer de la charge réseau:"
echo "   python3 tests/network_load_generator.py --namespace $NEXSLICE_NAMESPACE"
echo ""
echo "2. Lancer le benchmark HPA vs ML:"
echo "   python3 tests/benchmark.py"
echo ""
echo "3. Surveiller l'autoscaling en temps réel:"
echo "   $KUBECTL_CMD logs -f -n $NEXSLICE_NAMESPACE -l app=ml-autoscaler"
echo ""
echo "4. Voir les métriques Prometheus:"
echo "   $KUBECTL_CMD port-forward -n $MONITORING_NAMESPACE svc/prometheus 9090:9090"
echo "   Puis: http://localhost:9090"
echo ""
echo "5. Valider le déploiement:"
echo "   ./validate-deployment.sh"
echo ""
echo "6. Nettoyer si nécessaire:"
echo "   ./cleanup-nexslice.sh"
echo ""
echo "📖 Documentation complète disponible dans README.md"