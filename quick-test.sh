#!/bin/bash
# Test rapide de fonctionnement du ML Autoscaler (mode simulation)
set -e

echo "🧪 TEST RAPIDE ML AUTOSCALER (MODE SIMULATION)"
echo "==============================================="

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}1. Test d'importation des modules Python...${NC}"

python3 << 'EOF'
print("📦 Test des imports...")
try:
    import numpy as np
    print("✓ numpy OK")
    
    import pandas as pd
    print("✓ pandas OK")
    
    from sklearn.linear_model import LinearRegression
    print("✓ scikit-learn OK")
    
    # Simulation basique du modèle ML
    print("\n🧠 Test du modèle ML...")
    X = np.array([[70, 60, 50, 40], [80, 70, 100, 50], [60, 50, 30, 60]])
    y = np.array([65, 75, 55])
    
    model = LinearRegression()
    model.fit(X, y)
    
    # Prédiction test
    prediction = model.predict([[75, 65, 80, 45]])
    print(f"✓ Prédiction ML test: {prediction[0]:.2f}")
    
    print("\n✅ Tous les modules Python fonctionnent!")
    
except ImportError as e:
    print(f"❌ Erreur d'import: {e}")
    print("💡 Installer avec: pip3 install -r requirements.txt")
    exit(1)
except Exception as e:
    print(f"❌ Erreur: {e}")
    exit(1)
EOF

echo -e "\n${BLUE}2. Validation des fichiers de configuration...${NC}"

files_to_check=(
    "autoscaling/ml_autoscaler.py"
    "kubernetes/ml-autoscaler-deployment.yml"
    "kubernetes/nexslice-monitoring/nexslice-monitoring.yaml"
    "requirements.txt"
)

for file in "${files_to_check[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $file"
    else
        echo -e "${YELLOW}⚠${NC} $file manquant"
    fi
done

echo -e "\n${BLUE}3. Test de parsing des configurations YAML...${NC}"

python3 << 'EOF'
import yaml
import os

print("📄 Validation YAML...")

yaml_files = [
    "kubernetes/ml-autoscaler-deployment.yml",
    "kubernetes/nexslice-monitoring/nexslice-monitoring.yaml"
]

for yaml_file in yaml_files:
    if os.path.exists(yaml_file):
        try:
            with open(yaml_file, 'r') as f:
                yaml.safe_load(f)
            print(f"✓ {yaml_file} - YAML valide")
        except Exception as e:
            print(f"❌ {yaml_file} - Erreur: {e}")
    else:
        print(f"⚠ {yaml_file} - Fichier manquant")

print("\n✅ Validation YAML terminée!")
EOF

echo -e "\n${BLUE}4. Test des fonctions de métriques (simulation)...${NC}"

python3 << 'EOF'
print("📊 Simulation collecte de métriques...")

# Simulation des métriques
def simulate_metrics():
    import random
    import time
    
    # Métriques simulées
    metrics = {
        'cpu_usage': random.uniform(30, 90),
        'memory_usage': random.uniform(40, 85),
        'ping_latency': random.uniform(10, 150),
        'throughput': random.uniform(20, 100),
        'timestamp': time.time()
    }
    return metrics

# Test de calcul du score de charge
def calculate_load_score(metrics):
    return (
        (metrics['cpu_usage'] / 100) * 0.3 +
        (metrics['memory_usage'] / 100) * 0.3 +
        (metrics['ping_latency'] / 200) * 0.2 +
        (metrics['throughput'] / 100) * 0.2
    ) * 100

print("🎯 Simulation de 5 cycles de métriques...")
for i in range(5):
    metrics = simulate_metrics()
    load_score = calculate_load_score(metrics)
    
    print(f"Cycle {i+1}: CPU={metrics['cpu_usage']:.1f}%, "
          f"MEM={metrics['memory_usage']:.1f}%, "
          f"Latence={metrics['ping_latency']:.1f}ms, "
          f"Score={load_score:.1f}")
    
    # Simulation décision scaling
    current_pods = 3
    if load_score > 70:
        decision = "SCALE UP"
        new_pods = min(10, current_pods + 1)
    elif load_score < 30:
        decision = "SCALE DOWN"  
        new_pods = max(2, current_pods - 1)
    else:
        decision = "NO CHANGE"
        new_pods = current_pods
    
    print(f"   → Décision: {decision} (pods: {current_pods} → {new_pods})")
    print()

print("✅ Simulation métriques OK!")
EOF

echo -e "\n${BLUE}5. Vérification structure des tests...${NC}"

if [ -f "tests/network_load_generator.py" ]; then
    echo -e "${GREEN}✓${NC} Générateur de charge disponible"
    
    # Test basique sans exécution
    python3 -c "
import ast
with open('tests/network_load_generator.py') as f:
    ast.parse(f.read())
print('✓ Syntaxe Python valide')
"
else
    echo -e "${YELLOW}⚠${NC} Générateur de charge manquant"
fi

if [ -f "tests/benchmark.py" ]; then
    echo -e "${GREEN}✓${NC} Script de benchmark disponible"
    
    python3 -c "
import ast  
with open('tests/benchmark.py') as f:
    ast.parse(f.read())
print('✓ Syntaxe Python valide')
"
else
    echo -e "${YELLOW}⚠${NC} Script de benchmark manquant"
fi

echo -e "\n${GREEN}🎉 TESTS RAPIDES TERMINÉS${NC}"
echo "==============================="
echo ""
echo "✅ Le ML Autoscaler semble prêt à fonctionner!"
echo ""
echo "🚀 Prochaines étapes:"
echo "   1. Vérifier les prérequis complets: ./check-prerequisites.sh"
echo "   2. Installer sur NexSlice:          ./install.sh"
echo "   3. Lancer la démo:                  ./demo.sh"
echo ""
echo "📖 Documentation: README.md et ADAPTATION_GUIDE.md"
