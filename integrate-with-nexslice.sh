#!/bin/bash
# Script d'intégration avec le repository NexSlice existant
set -e

NEXSLICE_REPO_PATH=${1:-"/path/to/NexSlice"}
CURRENT_DIR=$(pwd)

echo "=== Intégration avec NexSlice Repository ==="
echo "Repo NexSlice: $NEXSLICE_REPO_PATH"

# Vérification que le repo NexSlice existe
if [ ! -d "$NEXSLICE_REPO_PATH" ]; then
    echo "Erreur: Le repository NexSlice n'existe pas à $NEXSLICE_REPO_PATH"
    echo "Usage: $0 <path-to-nexslice-repo>"
    echo "Exemple: $0 /Users/as/Documents/Projets/NexSlice"
    exit 1
fi

# Vérification des dossiers NexSlice critiques
required_dirs=("5g_core" "5g_ran" "monitoring")
for dir in "${required_dirs[@]}"; do
    if [ ! -d "$NEXSLICE_REPO_PATH/$dir" ]; then
        echo "Erreur: Dossier $dir manquant dans NexSlice"
        exit 1
    fi
done

echo "✓ Repository NexSlice validé"

# Création du dossier ml-autoscaler dans NexSlice
ML_AUTOSCALER_DIR="$NEXSLICE_REPO_PATH/ml-autoscaler"
mkdir -p "$ML_AUTOSCALER_DIR"

# Copie des fichiers essentiels
echo "Copie des composants ML Autoscaler..."

# Copie des scripts Python
cp -r autoscaling/ "$ML_AUTOSCALER_DIR/"
cp -r tests/ "$ML_AUTOSCALER_DIR/"

# Copie des configurations Kubernetes
cp -r kubernetes/ "$ML_AUTOSCALER_DIR/"

# Copie des fichiers de configuration
cp requirements.txt "$ML_AUTOSCALER_DIR/"
cp Dockerfile "$ML_AUTOSCALER_DIR/"
cp cleanup.sh "$ML_AUTOSCALER_DIR/"

# Création d'un script d'installation spécifique pour NexSlice
cat > "$ML_AUTOSCALER_DIR/install-nexslice.sh" << 'EOF'
#!/bin/bash
# Installation ML Autoscaler pour NexSlice
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEXSLICE_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Installation ML Autoscaler pour NexSlice ==="
echo "Répertoire NexSlice: $NEXSLICE_ROOT"

# Vérification que NexSlice est déployé
if ! kubectl get namespace nexslice &> /dev/null; then
    echo "Erreur: NexSlice n'est pas déployé (namespace 'nexslice' introuvable)"
    echo "Veuillez d'abord déployer NexSlice selon la documentation"
    exit 1
fi

# Vérification que le monitoring est actif
if ! kubectl get namespace monitoring &> /dev/null; then
    echo "Déploiement du monitoring NexSlice..."
    kubectl create namespace monitoring
    helm install monitoring "$NEXSLICE_ROOT/monitoring/" -n monitoring
fi

# Installation des dépendances Python
echo "Installation des dépendances Python..."
pip3 install -r "$SCRIPT_DIR/requirements.txt"

# Déploiement des configurations étendues de monitoring
echo "Déploiement de la configuration de monitoring étendue..."
kubectl apply -f "$SCRIPT_DIR/kubernetes/nexslice-monitoring/nexslice-monitoring.yaml"

# Mise à jour de la configuration Prometheus existante
echo "Mise à jour de la configuration Prometheus..."
PROMETHEUS_CONFIG="$NEXSLICE_ROOT/monitoring/charts/prometheus/values.yaml"
if [ -f "$PROMETHEUS_CONFIG" ]; then
    # Backup de la configuration existante
    cp "$PROMETHEUS_CONFIG" "$PROMETHEUS_CONFIG.backup"
    
    # Ajout des règles ML Autoscaler
    cat >> "$PROMETHEUS_CONFIG" << 'YAML_END'

# Configuration ML Autoscaler ajoutée automatiquement
serverFiles:
  nexslice_ml_rules.yml: |
    groups:
    - name: nexslice_ml_autoscaling
      rules:
      - record: nexslice:vnf_load_score
        expr: |
          (
            (rate(container_cpu_usage_seconds_total{pod=~".*smf.*|.*upf.*"}[5m]) * 100 / 100) * 0.3 +
            (container_memory_usage_bytes{pod=~".*smf.*|.*upf.*"} / container_spec_memory_limit_bytes) * 0.3 +
            (probe_duration_seconds{job="blackbox"} * 1000 / 200) * 0.2 +
            (rate(container_network_transmit_bytes_total{namespace="nexslice"}[5m]) / 1024 / 1024 / 100) * 0.2
          ) * 100
YAML_END

    echo "✓ Configuration Prometheus mise à jour"
else
    echo "⚠ Configuration Prometheus non trouvée, utilisation de la configuration par défaut"
fi

# Construction de l'image Docker ML Autoscaler
echo "Construction de l'image Docker..."
if command -v docker &> /dev/null; then
    docker build -t nexslice/ml-autoscaler:latest "$SCRIPT_DIR"
    echo "✓ Image Docker construite: nexslice/ml-autoscaler:latest"
else
    echo "⚠ Docker non disponible, utilisation de l'image par défaut"
fi

# Déploiement du ML Autoscaler
echo "Déploiement du ML Autoscaler..."
kubectl create configmap ml-autoscaler-code \
    --from-file="$SCRIPT_DIR/autoscaling/ml_autoscaler.py" \
    -n nexslice \
    --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f "$SCRIPT_DIR/kubernetes/ml-autoscaler-deployment.yml"

# Attente du démarrage
echo "Attente du démarrage des composants..."
kubectl wait --for=condition=ready pod -l app=ml-autoscaler -n nexslice --timeout=300s

echo ""
echo "=== Installation terminée! ==="
echo ""
echo "État du déploiement:"
kubectl get pods -n nexslice -l app=ml-autoscaler
echo ""
echo "Pour tester le système:"
echo "  cd $SCRIPT_DIR"
echo "  python3 tests/network_load_generator.py"
echo ""
echo "Pour surveiller les logs:"
echo "  kubectl logs -f -n nexslice -l app=ml-autoscaler"
EOF

chmod +x "$ML_AUTOSCALER_DIR/install-nexslice.sh"

# Mise à jour du README principal de NexSlice
echo "Mise à jour de la documentation NexSlice..."

# Backup du README existant
cp "$NEXSLICE_REPO_PATH/README.md" "$NEXSLICE_REPO_PATH/README.md.backup"

# Ajout de la section ML Autoscaler
cat >> "$NEXSLICE_REPO_PATH/README.md" << 'README_END'

## ML-based Autoscaling (Extension)

NexSlice inclut désormais un système d'autoscaling intelligent basé sur machine learning qui améliore l'HPA traditionnel de Kubernetes pour les VNFs 5G.

### Fonctionnalités

- **Prédiction proactive**: Modèle ML qui prédit la charge basée sur les métriques réseau
- **Métriques réseau avancées**: Intégration de latence (ping) et throughput (iPerf3)
- **Autoscaling intelligent**: Scaling des pods SMF/UPF basé sur des prédictions ML
- **Comparaison de performance**: Benchmarking automatique HPA vs ML

### Installation rapide

```bash
cd ml-autoscaler
./install-nexslice.sh
```

### Tests de performance

```bash
# Génération de charge réseau
cd ml-autoscaler
python3 tests/network_load_generator.py

# Benchmark complet HPA vs ML
python3 tests/benchmark.py
```

### Surveillance

```bash
# Logs de l'autoscaler ML
kubectl logs -f -n nexslice -l app=ml-autoscaler

# Métriques dans Grafana
kubectl port-forward -n monitoring svc/grafana 3000:3000
```

Pour plus de détails, consultez `ml-autoscaler/README.md`.
README_END

# Création d'un fichier de configuration pour l'intégration
cat > "$ML_AUTOSCALER_DIR/nexslice-integration.yaml" << 'YAML_END'
# Configuration d'intégration ML Autoscaler avec NexSlice
apiVersion: v1
kind: ConfigMap
metadata:
  name: nexslice-ml-config
  namespace: nexslice
data:
  # Déploiements ciblés pour l'autoscaling
  target_deployments: |
    - oai-smf
    - oai-upf
  
  # Configuration des seuils
  thresholds: |
    cpu_threshold: 70
    memory_threshold: 80
    latency_threshold_ms: 100
    throughput_threshold_mbps: 50
  
  # Configuration du modèle ML
  ml_model_config: |
    model_type: "linear_regression"  # ou "random_forest"
    training_window: 100
    prediction_interval: 30
    features_weights:
      cpu: 0.3
      memory: 0.3
      latency: 0.2
      throughput: 0.2
---
apiVersion: v1
kind: Secret
metadata:
  name: nexslice-ml-secrets
  namespace: nexslice
type: Opaque
data:
  # Base64 encoded prometheus URL
  prometheus_url: aHR0cDovL3Byb21ldGhldXM6OTA5MA==  # http://prometheus:9090
YAML_END

echo ""
echo "=== Intégration terminée avec succès! ==="
echo ""
echo "Fichiers ajoutés à NexSlice:"
echo "  $ML_AUTOSCALER_DIR/"
echo ""
echo "Prochaines étapes:"
echo "1. Allez dans le répertoire NexSlice:"
echo "   cd $NEXSLICE_REPO_PATH"
echo ""
echo "2. Installez l'autoscaler ML:"
echo "   cd ml-autoscaler && ./install-nexslice.sh"
echo ""
echo "3. Testez le système:"
echo "   python3 tests/network_load_generator.py"
echo ""
echo "Documentation mise à jour dans:"
echo "  $NEXSLICE_REPO_PATH/README.md"
echo "  $ML_AUTOSCALER_DIR/README.md"
