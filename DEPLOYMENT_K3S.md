# Guide de Déploiement sur K3s Local

Ce guide vous explique comment déployer le ML Autoscaler sur votre PC avec K3s.

## Prérequis

### 1. Installation de K3s

```bash
# Installation de K3s (si pas déjà installé)
curl -sfL https://get.k3s.io | sh -

# Configurer kubectl pour utiliser K3s
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $USER ~/.kube/config
export KUBECONFIG=~/.kube/config

# Vérifier que K3s fonctionne
kubectl get nodes
```

### 2. Installation de Prometheus et Grafana

```bash
# Créer le namespace monitoring
kubectl create namespace monitoring

# Installer Prometheus avec Helm (recommandé)
# Si Helm n'est pas installé
brew install helm

# Ajouter le repo Prometheus Community
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Installer Prometheus et Grafana
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false

# Vérifier que Prometheus est déployé
kubectl get pods -n monitoring
```

## Déploiement du Projet

### Étape 1: Créer le namespace nexslice

```bash
kubectl create namespace nexslice
```

### Étape 2: Builder l'image Docker localement

```bash
# Depuis le dossier racine du projet
cd /Users/as/Documents/Projets/ml-autoscaler

# Builder l'image Docker
docker build -t ml-autoscaler:latest .

# Importer l'image dans K3s
# Pour K3s, sauvegarder l'image et l'importer
docker save ml-autoscaler:latest -o ml-autoscaler.tar
sudo k3s ctr images import ml-autoscaler.tar
rm ml-autoscaler.tar
```

### Étape 3: Créer les ConfigMaps

```bash
# ConfigMap pour le code de l'autoscaler
kubectl create configmap ml-autoscaler-config \
  --from-file=ml_autoscaler.py=autoscaling/ml_autoscaler.py \
  -n nexslice

# ConfigMap pour les requirements
kubectl create configmap ml-autoscaler-requirements \
  --from-file=requirements.txt \
  -n nexslice
```

### Étape 4: Déployer les configurations de monitoring

```bash
# Appliquer les règles Prometheus pour NexSlice
kubectl apply -f kubernetes/nexslice-monitoring/nexslice-monitoring.yaml
```

### Étape 5: Déployer le ML Autoscaler

```bash
# Déployer l'autoscaler
kubectl apply -f kubernetes/ml-autoscaler-deployment.yml
```

### Étape 6: Vérifier le déploiement

```bash
# Vérifier que les pods sont en cours d'exécution
kubectl get pods -n nexslice

# Voir les logs de l'autoscaler
kubectl logs -f -n nexslice -l app=ml-autoscaler

# Vérifier les services
kubectl get svc -n nexslice

# Vérifier les RBAC
kubectl get serviceaccount,clusterrole,clusterrolebinding | grep ml-autoscaler
```

## Configuration

### Modifier les variables d'environnement

Si vous devez modifier l'URL de Prometheus ou d'autres paramètres:

```bash
kubectl edit deployment ml-autoscaler -n nexslice
```

Modifiez la section `env`:
```yaml
env:
- name: PROMETHEUS_URL
  value: "http://prometheus-kube-prometheus-prometheus.monitoring:9090"
- name: NAMESPACE
  value: "nexslice"
```

### Accéder à Prometheus et Grafana

```bash
# Port-forward Prometheus
kubectl port-forward -n monitoring svc/prometheus-kube-prometheus-prometheus 9090:9090

# Port-forward Grafana (dans un autre terminal)
kubectl port-forward -n monitoring svc/prometheus-grafana 3000:80

# Obtenir le mot de passe Grafana
kubectl get secret -n monitoring prometheus-grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
```

Ensuite ouvrez:
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (user: admin)

## Tests

### Test 1: Vérifier la connexion à Prometheus

```bash
# Exécuter une commande dans le pod de l'autoscaler
kubectl exec -it -n nexslice deployment/ml-autoscaler -- python3 -c "
import requests
try:
    response = requests.get('http://prometheus-kube-prometheus-prometheus.monitoring:9090/api/v1/query?query=up')
    print('✓ Connexion à Prometheus réussie!')
    print(response.json())
except Exception as e:
    print(f'✗ Erreur: {e}')
"
```

### Test 2: Générer de la charge (si vous avez une application NexSlice)

```bash
# Utiliser le générateur de charge réseau
python3 tests/network_load_generator.py --namespace nexslice --max-tests 5
```

### Test 3: Benchmark complet

```bash
# Lancer le benchmark HPA vs ML
python3 tests/benchmark.py
```

## Débogage

### Problèmes courants

#### 1. L'autoscaler ne démarre pas

```bash
# Vérifier les événements
kubectl describe pod -n nexslice -l app=ml-autoscaler

# Vérifier les logs
kubectl logs -n nexslice -l app=ml-autoscaler --tail=100
```

#### 2. Impossible de se connecter à Prometheus

```bash
# Vérifier que Prometheus est accessible
kubectl get svc -n monitoring | grep prometheus

# Tester la connectivité
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- \
  curl http://prometheus-kube-prometheus-prometheus.monitoring:9090/api/v1/query?query=up
```

#### 3. Permissions insuffisantes

```bash
# Vérifier les RBAC
kubectl get clusterrolebinding ml-autoscaler-binding -o yaml

# Vérifier le ServiceAccount
kubectl get sa ml-autoscaler-sa -n nexslice
```

#### 4. Image Docker non trouvée

```bash
# Lister les images dans K3s
sudo k3s ctr images ls | grep ml-autoscaler

# Si l'image n'est pas là, la réimporter
docker save ml-autoscaler:latest -o ml-autoscaler.tar
sudo k3s ctr images import ml-autoscaler.tar
```

## Nettoyage

Pour supprimer complètement le déploiement:

```bash
# Supprimer le déploiement de l'autoscaler
kubectl delete -f kubernetes/ml-autoscaler-deployment.yml

# Supprimer les ConfigMaps
kubectl delete configmap ml-autoscaler-config -n nexslice
kubectl delete configmap ml-autoscaler-requirements -n nexslice

# Supprimer le namespace (optionnel)
kubectl delete namespace nexslice

# Supprimer Prometheus (optionnel)
helm uninstall prometheus -n monitoring
kubectl delete namespace monitoring
```

## Surveillance

### Métriques à surveiller

```bash
# Nombre de pods autoscalés
kubectl get pods -n nexslice -w

# Logs de l'autoscaler en temps réel
kubectl logs -f -n nexslice -l app=ml-autoscaler

# Métriques Prometheus
# Ouvrir http://localhost:9090 et exécuter:
# - nexslice:vnf_cpu_usage_percent
# - nexslice:vnf_memory_usage_percent
# - nexslice:network_latency_ms
# - nexslice:ml_scaling_decision
```

## Performance

Pour de meilleures performances sur votre PC:

```bash
# Ajuster les ressources du pod
kubectl edit deployment ml-autoscaler -n nexslice
```

Modifiez les `resources` selon la capacité de votre machine:
```yaml
resources:
  requests:
    memory: "128Mi"
    cpu: "50m"
  limits:
    memory: "256Mi"
    cpu: "100m"
```

## Prochaines étapes

1. **Déployer une application de test** dans le namespace `nexslice`
2. **Configurer des HPAs** pour comparer avec le ML Autoscaler
3. **Personnaliser le modèle ML** selon vos besoins
4. **Ajouter des dashboards Grafana** pour la visualisation

## Support

Pour plus d'informations, consultez:
- README.md - Documentation générale
- ADAPTATION_GUIDE.md - Guide d'adaptation
- autoscaling/ml_autoscaler.py - Code source commenté
