# NexSlice ML Autoscaler

Ce projet développe un système d'autoscaling horizontal adaptatif basé sur machine learning pour les VNFs (Virtual Network Functions) dans l'environnement NexSlice 5G. Il remplace l'HPA (Horizontal Pod Autoscaler) traditionnel de Kubernetes par un système intelligent qui analyse en temps réel la charge réseau (ping, iPerf3) et utilise un modèle ML pour prédire la charge future et ajuster automatiquement le nombre de pods SMF/UPF.

## Vue d'ensemble

### Problématique
- L'HPA Kubernetes réagit lentement et se base uniquement sur CPU/mémoire
- Provoque du sur-provisionnement ou sous-provisionnement
- Ne tient pas compte des métriques réseau spécifiques à la 5G

### Solution ML
- Analyse temps réel de la charge réseau (ping, iPerf3)
- Modèle ML pour prédiction à court terme
- Autoscaling proactif des pods SMF/UPF
- Métriques composites incluant latence et throughput

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   NexSlice      │    │   ML Autoscaler  │    │   Prometheus    │
│   (SMF/UPF)     │◄──►│   - Collecteur   │◄──►│   - Métriques   │
│   - Pods VNFs   │    │   - ML Predictor │    │   - Alertes     │
│   - UE Traffic  │    │   - Scaler       │    │   - Rules       │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         ▲                        ▲                        ▲
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  ▼
                         ┌──────────────────┐
                         │   Load Generator │
                         │   - iPerf3 Tests │
                         │   - Ping Tests   │
                         │   - Benchmarking │
                         └──────────────────┘
```

## Installation

### Prérequis

1. **NexSlice déployé** sur un cluster K3s/Kubernetes
2. **Prometheus et Grafana** installés dans le namespace `monitoring`
3. **Python 3.9+** avec pip
4. **kubectl** configuré pour accéder au cluster

### Installation automatique

```bash
git clone https://github.com/ksiksy/ml-autoscaler
cd ml-autoscaler
chmod +x install.sh
./install.sh
```

### Installation manuelle

1. **Installation des dépendances Python:**
```bash
pip3 install prometheus-api-client kubernetes numpy pandas scikit-learn matplotlib
```

2. **Déploiement des configurations de monitoring:**
```bash
kubectl apply -f kubernetes/nexslice-monitoring/nexslice-monitoring.yaml
```

3. **Déploiement du ML Autoscaler:**
```bash
kubectl create configmap ml-autoscaler-code --from-file=autoscaling/ml_autoscaler.py -n nexslice
kubectl apply -f kubernetes/ml-autoscaler-deployment.yml
```

## Utilisation

### 1. Génération de charge pour tester l'autoscaling

```bash
# Génère une charge graduellement croissante
python3 tests/network_load_generator.py --namespace nexslice --max-tests 10
```

### 2. Benchmark HPA vs ML Autoscaler

```bash
# Lance un benchmark complet (30 minutes)
python3 tests/benchmark.py
```

Le benchmark:
- Teste d'abord avec HPA Kubernetes (15 min)
- Puis avec ML Autoscaler (15 min)
- Génère des graphiques de comparaison
- Produit un rapport d'efficacité

### 3. Surveillance en temps réel

```bash
# Logs de l'autoscaler ML
kubectl logs -f -n nexslice -l app=ml-autoscaler

# État des pods VNFs
watch kubectl get pods -n nexslice

# Métriques Prometheus
kubectl port-forward -n monitoring svc/prometheus 9090:9090
```

## Métriques et modèle ML

### Métriques collectées
- **Latence réseau**: Tests ping vers targets externes
- **Throughput**: Tests iPerf3 entre UEs et serveurs
- **CPU/Mémoire**: Utilisation des pods SMF/UPF
- **Nombre de connexions**: Sessions actives

### Modèle ML
- **Type**: Linear Regression ou Random Forest
- **Features**: [latence, throughput, cpu, mémoire]
- **Target**: Score de charge composite
- **Apprentissage**: Incrémental avec historique glissant

### Score de charge composite
```python
load_score = (cpu_usage/100) * 0.3 + 
             (memory_usage/100) * 0.3 + 
             (ping_latency/200) * 0.2 + 
             (throughput/100) * 0.2
```

## Configuration

### Variables d'environnement (dans les deployments)
```yaml
env:
- name: PROMETHEUS_URL
  value: "http://prometheus:9090"
- name: NAMESPACE  
  value: "nexslice"
- name: CPU_THRESHOLD
  value: "70"
- name: MEMORY_THRESHOLD
  value: "80"
- name: MIN_REPLICAS
  value: "2"
- name: MAX_REPLICAS
  value: "10"
```

### Seuils de scaling
- **CPU**: 70% (seuil d'alarme)
- **Mémoire**: 80% (seuil d'alarme)
- **Latence**: 100ms (seuil acceptable)
- **Throughput**: 50MB/s (seuil critique)

## Résultats attendus

### Comparaison HPA vs ML Autoscaler

| Métrique | HPA | ML Autoscaler | Amélioration |
|----------|-----|---------------|-------------|
| Temps de réaction | 2-5 min | 30s-1min | 60-80% |
| Précision scaling | 60-70% | 85-95% | +25% |
| Gaspillage ressources | 20-30% | 5-15% | 50-70% |
| Stabilité | Oscillations | Stable | +40% |

### Métriques d'efficacité
- **Réduction des pods inutilisés**: 40-60%
- **Amélioration de la latence**: 20-30%  
- **Stabilité accrue**: 50% moins d'oscillations
- **Prédiction proactive**: 80% de précision

## Structure du projet

```
ml-autoscaler/
├── autoscaling/
│   ├── ml_autoscaler.py          # Autoscaler principal ML
│   └── k3s-autoscaling.service   # Service systemd
├── tests/
│   ├── network_load_generator.py # Générateur de charge
│   ├── benchmark.py              # Comparaison HPA vs ML
│   └── locust.py                # Tests de charge legacy
├── kubernetes/
│   ├── ml-autoscaler-deployment.yml
│   └── nexslice-monitoring/
│       ├── nexslice-monitoring.yaml
│       └── config-map.yaml
├── README.md
└── install.sh
```

## Développement et personnalisation

### Ajouter de nouvelles métriques

1. **Dans NetworkMetricsCollector:**
```python
def get_custom_metric(self):
    query = 'your_prometheus_query'
    data = self.prom.custom_query(query=query)
    return process_data(data)
```

2. **Dans MLPredictor:**
```python
# Ajouter la métrique aux features
current_features = [ping, throughput, cpu, memory, custom_metric]
```

### Modifier l'algorithme ML

```python
# Dans MLPredictor.__init__()
from sklearn.ensemble import RandomForestRegressor
self.model = RandomForestRegressor(
    n_estimators=100,
    max_depth=10,
    random_state=42
)
```

## Dépannage

### Problèmes courants

1. **Autoscaler ne démarre pas:**
```bash
kubectl describe pod -n nexslice -l app=ml-autoscaler
```

2. **Pas de métriques Prometheus:**
```bash
kubectl get svc -n monitoring prometheus
kubectl port-forward -n monitoring svc/prometheus 9090:9090
```

3. **Erreurs de permissions:**
```bash
kubectl describe clusterrolebinding ml-autoscaler-binding
```

### Debug mode
```bash
# Activer les logs détaillés
kubectl set env deployment/ml-autoscaler LOG_LEVEL=DEBUG -n nexslice
```

## Contribuer

1. Fork le repository
2. Créer une branche feature
3. Tester avec le benchmark
4. Soumettre une pull request

## Licence

MIT License - voir LICENSE file

## Références

- [NexSlice Project](https://github.com/AIDY-F2N/NexSlice)
- [Kubernetes HPA](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
- [Prometheus](https://prometheus.io/)
- [scikit-learn](https://scikit-learn.org/)
