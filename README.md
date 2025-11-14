# K3s Autoscaling
This project involves developing an auto-scaling cluster aiming to ensure the horizontal scaling of a Kubernetes cluster with cost-effective instances (AWS t2.medium and t2.micro) using K3s, Terraform, Python, and Prometheus.

The project serves as a proof of concept for a cluster consisting of 1 master node and initially 2 worker nodes. K3s is utilized to deploy Kubernetes, while Prometheus is used to gather node resource utilization, and Terraform is employed to define infrastructure as code and abstract the usage of the AWS API. The Python script runs as a service within the system, collecting information from Prometheus, performing scaling calculations, and applying the Terraform manifest to increase or decrease the cluster's node count.

The Python code determines the scaling decision based on the following formula:

desired_replica_count = ceil[current_replica_count * (current_metric_value / desired_metric_value)]

## Install and use
### Prerequisite
install terraform: https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli

### Install
- Clone the repo to your local machine
```
git clone https://github.com/matheus-nicolay/k3s-autoscaling
```
- Setup AWS credentials `AWS_REGION`, `AWS_ACCESS_KEY` and `AWS_SECRET_KEY`:
```
nano variables.conf
```

- Give run permission and execute the install script
```
chmod +x install.sh
./install.sh
```
