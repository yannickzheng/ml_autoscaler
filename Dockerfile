# Utilisation d'une image légère de Python
FROM python:3.9-slim

# Configuration des variables d'environnement
ENV PYTHONUNBUFFERED=1
ENV PROMETHEUS_URL="http://prometheus:9090"

# Création du dossier de travail
WORKDIR /app

# Installation des dépendances système nécessaires pour scikit-learn/numpy
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copie et installation des requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du code source
COPY autoscaling/ml_autoscaler.py .

# Création d'un utilisateur non-root pour la sécurité
RUN useradd -m autoscaler
USER autoscaler

# Commande de démarrage
CMD ["python3", "ml_autoscaler.py"]