#!/bin/bash
vpc_dir="./terraform/vpc"

master_node_dir="./terraform/master_node"
worker_node_dir="./terraform/worker_node"

echo "Applying Terraform for VPC and Master Node..."
cd "$master_node_dir" || exit
terraform init
terraform apply \
    -var "region=$(grep -oP '^AWS_REGION="\K[^"]+' ../../variables.conf)" \
    -var "access_key=$(grep -oP '^AWS_ACCESS_KEY="\K[^"]+' ../../variables.conf)" \
    -var "secret_key=$(grep -oP '^AWS_SECRET_KEY="\K[^"]+' ../../variables.conf)" \
    -auto-approve