#!/bin/bash
# Vérification des prérequis pour ML Autoscaler NexSlice
set -e

echo "🔍 VÉRIFICATION DES PRÉREQUIS ML AUTOSCALER"
echo "============================================"

# Couleurs
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

check_ok() { echo -e "${GREEN}✓${NC} $1"; }
check_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
check_error() { echo -e "${RED}✗${NC} $1"; }

errors=0
warnings=0

echo "🐳 Vérification de K3s/Kubernetes..."

# Vérification K3s
if command -v k3s &> /dev/null; then
    check_ok "K3s installé"
    K3S_AVAILABLE=true
    KUBECTL_CMD="sudo k3s kubectl"
elif command -v kubectl &> /dev/null; then
    check_warn "kubectl disponible (K3s recommandé pour NexSlice)"
    K3S_AVAILABLE=false
    KUBECTL_CMD="kubectl"
else
    check_error "Ni K3s ni kubectl installé"
    echo "   Installation K3s: curl -sfL https://get.k3s.io | sh -"
    ((errors++))
    exit 1
fi

# Test de connectivité cluster
echo -e "\n🔌 Test de connectivité au cluster..."
if $KUBECTL_CMD cluster-info &> /dev/null; then
    check_ok "Connexion au cluster réussie"
    
    # Vérification des namespaces NexSlice
    if $KUBECTL_CMD get namespace nexslice &> /dev/null; then
        check_ok "Namespace 'nexslice' trouvé"
        
        # Vérification des composants NexSlice essentiels
        core_components=("oai-amf" "oai-smf" "oai-upf")
        nexslice_ready=true
        
        for component in "${core_components[@]}"; do
            if $KUBECTL_CMD get deployment "$component" -n nexslice &> /dev/null; then
                pods_ready=$($KUBECTL_CMD get deployment "$component" -n nexslice -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
                if [ "${pods_ready:-0}" -gt 0 ]; then
                    check_ok "Composant $component déployé et prêt"
                else
                    check_warn "Composant $component déployé mais non prêt"
                    nexslice_ready=false
                    ((warnings++))
                fi
            else
                check_error "Composant $component manquant"
                nexslice_ready=false
                ((errors++))
            fi
        done
        
    else
        check_error "Namespace 'nexslice' non trouvé"
        echo "   Veuillez d'abord déployer NexSlice selon la documentation"
        ((errors++))
        nexslice_ready=false
    fi
else
    check_error "Impossible de se connecter au cluster"
    echo "   Vérifiez que K3s est démarré: sudo systemctl status k3s"
    ((errors++))
fi

# Vérification Monitoring
echo -e "\n📊 Vérification du monitoring..."
if $KUBECTL_CMD get namespace monitoring &> /dev/null; then
    check_ok "Namespace 'monitoring' trouvé"
    
    # Vérification Prometheus
    if $KUBECTL_CMD get deployment -n monitoring | grep -q prometheus; then
        check_ok "Prometheus déployé"
    else
        check_warn "Prometheus non déployé (sera installé automatiquement)"
        ((warnings++))
    fi
    
    # Vérification Grafana
    if $KUBECTL_CMD get deployment -n monitoring | grep -q grafana; then
        check_ok "Grafana déployé"
    else
        check_warn "Grafana non déployé (optionnel)"
        ((warnings++))
    fi
else
    check_warn "Namespace 'monitoring' non trouvé (sera créé)"
    ((warnings++))
fi

# Vérification Python
echo -e "\n🐍 Vérification de Python..."
if command -v python3 &> /dev/null; then
    python_version=$(python3 --version | cut -d' ' -f2)
    check_ok "Python3 installé (version $python_version)"
    
    if command -v pip3 &> /dev/null; then
        check_ok "pip3 disponible"
        
        # Vérification des dépendances critiques
        critical_deps=("prometheus-api-client" "kubernetes" "numpy" "scikit-learn")
        deps_missing=()
        
        for dep in "${critical_deps[@]}"; do
            if python3 -c "import $dep" &> /dev/null 2>&1 || python3 -c "import ${dep//-/_}" &> /dev/null 2>&1; then
                check_ok "Dépendance $dep installée"
            else
                deps_missing+=("$dep")
                check_warn "Dépendance $dep manquante"
                ((warnings++))
            fi
        done
        
        if [ ${#deps_missing[@]} -gt 0 ]; then
            echo "   Installation: pip3 install ${deps_missing[*]}"
        fi
    else
        check_warn "pip3 non trouvé"
        echo "   Installation: python3 -m ensurepip --upgrade"
        ((warnings++))
    fi
else
    check_error "Python3 non installé"
    ((errors++))
fi

# Vérification outils réseau
echo -e "\n🌐 Vérification outils réseau..."
if command -v ping &> /dev/null; then
    check_ok "ping disponible"
else
    check_warn "ping non disponible (tests de latence limités)"
    ((warnings++))
fi

if command -v iperf3 &> /dev/null; then
    check_ok "iperf3 disponible"
else
    check_warn "iperf3 non disponible (installation recommandée)"
    echo "   Installation: sudo apt install iperf3 (Ubuntu) ou brew install iperf3 (macOS)"
    ((warnings++))
fi

# Vérification ressources système
echo -e "\n💻 Vérification ressources système..."
available_memory=$(free -m 2>/dev/null | awk 'NR==2{printf "%.0f", $7}' || echo "N/A")
if [ "$available_memory" != "N/A" ]; then
    if [ "$available_memory" -gt 2048 ]; then
        check_ok "Mémoire disponible suffisante (${available_memory}MB)"
    else
        check_warn "Mémoire disponible faible (${available_memory}MB)"
        ((warnings++))
    fi
fi

# Test d'accès réseau externe
echo -e "\n🌍 Test connectivité Internet..."
if ping -c 1 8.8.8.8 &> /dev/null; then
    check_ok "Connectivité Internet OK"
else
    check_warn "Connectivité Internet limitée"
    ((warnings++))
fi

# Résumé final
echo -e "\n📋 RÉSUMÉ DES PRÉREQUIS"
echo "======================"

if [ $errors -eq 0 ]; then
    if [ $warnings -eq 0 ]; then
        echo -e "${GREEN}🎉 Tous les prérequis sont satisfaits !${NC}"
        echo "   Vous pouvez maintenant installer ML Autoscaler:"
        echo "   ./install.sh"
    else
        echo -e "${YELLOW}⚠️  Prérequis principaux OK avec $warnings avertissement(s)${NC}"
        echo "   Installation possible mais certaines fonctionnalités peuvent être limitées"
        echo "   ./install.sh"
    fi
else
    echo -e "${RED}❌ $errors erreur(s) critique(s) détectée(s)${NC}"
    echo "   Veuillez corriger les erreurs avant l'installation"
    
    if [ "$nexslice_ready" = false ]; then
        echo -e "\n🎯 ACTIONS REQUISES:"
        echo "   1. Déployer NexSlice complet selon la documentation"
        echo "   2. Vérifier que les composants SMF/UPF sont actifs"
        echo "   3. Relancer cette vérification: ./check-prerequisites.sh"
    fi
fi

exit $errors
