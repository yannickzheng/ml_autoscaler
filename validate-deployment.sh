#!/bin/bash
# Script de validation du déploiement ML Autoscaler pour NexSlice
set -e

echo "=== Validation du déploiement ML Autoscaler ==="

NAMESPACE="nexslice"
MONITORING_NAMESPACE="monitoring"

# Couleurs pour l'affichage
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Fonction d'affichage coloré
print_status() {
    local status=$1
    local message=$2
    case $status in
        "OK")
            echo -e "${GREEN}✓${NC} $message"
            ;;
        "WARN")
            echo -e "${YELLOW}⚠${NC} $message"
            ;;
        "ERROR")
            echo -e "${RED}✗${NC} $message"
            ;;
    esac
}

# Fonction de vérification
check_component() {
    local component=$1
    local namespace=$2
    local selector=$3
    
    echo -n "Vérification de $component... "
    
    if kubectl get pods -n "$namespace" -l "$selector" &> /dev/null; then
        local ready_pods=$(kubectl get pods -n "$namespace" -l "$selector" -o jsonpath='{.items[*].status.conditions[?(@.type=="Ready")].status}' | grep -o "True" | wc -l)
        local total_pods=$(kubectl get pods -n "$namespace" -l "$selector" --no-headers | wc -l)
        
        if [ "$ready_pods" -eq "$total_pods" ] && [ "$total_pods" -gt 0 ]; then
            print_status "OK" "$component ($ready_pods/$total_pods pods prêts)"
            return 0
        else
            print_status "WARN" "$component ($ready_pods/$total_pods pods prêts)"
            return 1
        fi
    else
        print_status "ERROR" "$component (non trouvé)"
        return 1
    fi
}

# Vérification de la connectivité au cluster
echo "Vérification de la connectivité Kubernetes..."
if kubectl cluster-info &> /dev/null; then
    print_status "OK" "Connectivité Kubernetes"
else
    print_status "ERROR" "Impossible de se connecter au cluster Kubernetes"
    exit 1
fi

# Vérification des namespaces
echo -e "\nVérification des namespaces..."
for ns in "$NAMESPACE" "$MONITORING_NAMESPACE"; do
    if kubectl get namespace "$ns" &> /dev/null; then
        print_status "OK" "Namespace $ns"
    else
        print_status "ERROR" "Namespace $ns manquant"
    fi
done

# Vérification des composants NexSlice Core
echo -e "\nVérification des composants NexSlice Core..."
core_components=("app=oai-amf" "app=oai-smf" "app=oai-upf" "app=mysql")
for component in "${core_components[@]}"; do
    check_component "$(echo $component | cut -d'=' -f2 | tr '[:lower:]' '[:upper:]')" "$NAMESPACE" "$component"
done

# Vérification du ML Autoscaler
echo -e "\nVérification du ML Autoscaler..."
check_component "ML Autoscaler" "$NAMESPACE" "app=ml-autoscaler"

# Vérification du monitoring
echo -e "\nVérification du monitoring..."
monitoring_components=("app=prometheus" "app=grafana" "app=blackbox-exporter")
for component in "${monitoring_components[@]}"; do
    check_component "$(echo $component | cut -d'=' -f2 | tr '[:lower:]' '[:upper:]')" "$MONITORING_NAMESPACE" "$component"
done

# Vérification des services
echo -e "\nVérification des services..."
services=("oai-smf" "oai-upf" "ml-autoscaler-metrics")
for service in "${services[@]}"; do
    if kubectl get service "$service" -n "$NAMESPACE" &> /dev/null; then
        print_status "OK" "Service $service"
    else
        print_status "WARN" "Service $service manquant"
    fi
done

# Vérification des ConfigMaps
echo -e "\nVérification des ConfigMaps..."
configmaps=("ml-autoscaler-code" "ml-autoscaler-config")
for cm in "${configmaps[@]}"; do
    if kubectl get configmap "$cm" -n "$NAMESPACE" &> /dev/null; then
        print_status "OK" "ConfigMap $cm"
    else
        print_status "WARN" "ConfigMap $cm manquant"
    fi
done

# Test de connectivité Prometheus
echo -e "\nTest de connectivité Prometheus..."
if kubectl get service prometheus -n "$MONITORING_NAMESPACE" &> /dev/null; then
    # Port-forward temporaire pour tester
    kubectl port-forward -n "$MONITORING_NAMESPACE" svc/prometheus 9090:9090 &
    PF_PID=$!
    sleep 3
    
    if curl -s "http://localhost:9090/api/v1/query?query=up" | grep -q "success"; then
        print_status "OK" "Prometheus API accessible"
    else
        print_status "WARN" "Prometheus API non accessible"
    fi
    
    kill $PF_PID &> /dev/null || true
else
    print_status "ERROR" "Service Prometheus non trouvé"
fi

# Vérification des métriques ML Autoscaler
echo -e "\nVérification des métriques personnalisées..."
custom_metrics=("nexslice:vnf_cpu_usage_percent" "nexslice:network_latency_ms" "nexslice:total_vnf_pods")

if kubectl get service prometheus -n "$MONITORING_NAMESPACE" &> /dev/null; then
    kubectl port-forward -n "$MONITORING_NAMESPACE" svc/prometheus 9090:9090 &
    PF_PID=$!
    sleep 3
    
    for metric in "${custom_metrics[@]}"; do
        if curl -s "http://localhost:9090/api/v1/query?query=$metric" | grep -q "success"; then
            print_status "OK" "Métrique $metric"
        else
            print_status "WARN" "Métrique $metric non disponible"
        fi
    done
    
    kill $PF_PID &> /dev/null || true
fi

# Test des permissions RBAC
echo -e "\nVérification des permissions RBAC..."
rbac_resources=("clusterrole/ml-autoscaler-role" "clusterrolebinding/ml-autoscaler-binding" "serviceaccount/ml-autoscaler-sa")
for resource in "${rbac_resources[@]}"; do
    if kubectl get "$resource" &> /dev/null; then
        print_status "OK" "RBAC $resource"
    else
        print_status "WARN" "RBAC $resource manquant"
    fi
done

# Vérification des logs ML Autoscaler
echo -e "\nVérification des logs ML Autoscaler..."
ML_POD=$(kubectl get pods -n "$NAMESPACE" -l app=ml-autoscaler -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ ! -z "$ML_POD" ]; then
    echo "Pod ML Autoscaler: $ML_POD"
    
    # Vérifie si le pod a des logs récents (dernières 2 minutes)
    recent_logs=$(kubectl logs --since=2m -n "$NAMESPACE" "$ML_POD" 2>/dev/null | wc -l)
    if [ "$recent_logs" -gt 0 ]; then
        print_status "OK" "ML Autoscaler produit des logs ($recent_logs lignes récentes)"
        echo "Derniers logs:"
        kubectl logs --tail=3 -n "$NAMESPACE" "$ML_POD" | sed 's/^/    /'
    else
        print_status "WARN" "ML Autoscaler ne produit pas de logs récents"
    fi
else
    print_status "ERROR" "Pod ML Autoscaler non trouvé"
fi

# Test de connectivité réseau
echo -e "\nTest de connectivité réseau (UE vers Internet)..."
UE_PODS=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=ueransim-ue -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)
if [ ! -z "$UE_PODS" ]; then
    UE_POD=$(echo $UE_PODS | awk '{print $1}')
    if kubectl exec -n "$NAMESPACE" "$UE_POD" -- ping -c 2 -W 3 8.8.8.8 &> /dev/null; then
        print_status "OK" "Connectivité UE vers Internet"
    else
        print_status "WARN" "Problème de connectivité UE vers Internet"
    fi
else
    print_status "WARN" "Aucun pod UE trouvé pour test de connectivité"
fi

# Résumé final
echo -e "\n=== RÉSUMÉ DE LA VALIDATION ==="

# Compte des composants
total_components=0
working_components=0

# Fonction pour compter les résultats
count_results() {
    local check_output="$1"
    local total=$(echo "$check_output" | grep -E "✓|⚠|✗" | wc -l)
    local working=$(echo "$check_output" | grep "✓" | wc -l)
    echo "$working/$total"
}

echo "État du déploiement ML Autoscaler pour NexSlice:"
echo ""
echo "📊 Statistiques:"
echo "   - Composants principaux: $(count_results "$(check_component "test" "$NAMESPACE" "app=oai-smf,app=oai-upf,app=ml-autoscaler" 2>&1)")"
echo "   - Monitoring: $(count_results "$(check_component "test" "$MONITORING_NAMESPACE" "app=prometheus,app=grafana" 2>&1)")"
echo ""

if kubectl get pods -n "$NAMESPACE" -l app=ml-autoscaler | grep -q Running; then
    echo "🎉 ML Autoscaler est déployé et fonctionne!"
    echo ""
    echo "Commandes utiles:"
    echo "   📊 Surveiller les logs:      kubectl logs -f -n $NAMESPACE -l app=ml-autoscaler"
    echo "   📈 Accéder à Grafana:        kubectl port-forward -n $MONITORING_NAMESPACE svc/grafana 3000:3000"
    echo "   🔍 Métriques Prometheus:     kubectl port-forward -n $MONITORING_NAMESPACE svc/prometheus 9090:9090"
    echo "   🧪 Lancer un test:           python3 tests/network_load_generator.py"
    echo "   📊 Benchmark complet:        python3 tests/benchmark.py"
else
    echo "❌ ML Autoscaler n'est pas correctement déployé"
    echo ""
    echo "Pour diagnostiquer:"
    echo "   kubectl describe pods -n $NAMESPACE -l app=ml-autoscaler"
    echo "   kubectl logs -n $NAMESPACE -l app=ml-autoscaler"
fi

echo ""
echo "Pour plus d'aide, consultez README.md"
