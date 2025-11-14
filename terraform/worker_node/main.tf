variable "region" {
  type = string
}

variable "access_key" {
  type = string
}

variable "secret_key" {
  type = string
}

provider "aws" {
  region      = var.region 
  access_key  = var.access_key 
  secret_key  = var.secret_key 
}

data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["099720109477"] # Canonical
}

resource "aws_instance" "kubernetes_worker01" {
  ami           = data.aws_ami.ubuntu.id
  instance_type = "t2.micro"
  count=2
  key_name = "kubernetes_cluster_key" # Insira o nome da chave criada antes.
  subnet_id = aws_subnet.Public_subnet.id
  vpc_security_group_ids = [aws_security_group.permitir_ssh_http_nodes.id]
  associate_public_ip_address = true

  tags = {
    Name = "k3s_worker-${count.index}"
    type = "k3s"
    # Insira o nome da instância de sua preferência.
  }

  connection {
    type     = "ssh"
    user     = "ubuntu"
    private_key = file("kubernetes_cluster_key.pem")
    host     = self.public_ip
  }

  provisioner "remote-exec" {
    inline = [
      "sudo hostnamectl set-hostname k3sworker-${self.private_ip}",
      "curl -sfL https://get.k3s.io | K3S_URL=${var.k3s_url} K3S_TOKEN=${var.k3s_token} sh -",
      "sed -i 's#k3s.example#${aws_elb.k3s-elb.dns_name}#g' /opt/k3s-autoscaling/autoscaling/k3s-autoscaling.py",
      "echo 'LoadBalancer address: http://${aws_elb.k3s-elb.dns_name}:8080'"
    ]
  }
}

resource "aws_security_group" "permitir_ssh_http_nodes" {
  name        = "permitir_ssh_http_worker01"
  description = "Permite SSH e HTTP na instancia EC2"
  vpc_id      = aws_vpc.VPC_cluster_kubernetes.id

    ingress {
    description = "SSH to EC2"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP to EC2"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS to EC2"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "K3S to EC2"
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "K3S to EC2-1"
    from_port   = 8472
    to_port     = 8472
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Kubelet metrics"
    from_port   = 10250
    to_port     = 10250
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Kubelet2"
    from_port   = 16443
    to_port     = 16443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Flannel Wireguard "
    from_port   = 51820
    to_port     = 51820
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "all traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

}

data "aws_instances" "k3s_workers" {
  instance_tags = {
    type = "k3s"
  }

  instance_state_names = ["running"]
}

output "instances" {
  value = "${data.aws_instances.k3s_workers.ids}"
}

# Create a new load balancer
resource "aws_elb" "k3s-elb" {
  name               = "k3s-elb"

  health_check {
    healthy_threshold   = 2
    unhealthy_threshold = 2
    timeout             = 3
    target              = "TCP:22"
    interval            = 30
  }

  listener {
    instance_port     = 31977
    instance_protocol = "tcp"
    lb_port           = 80
    lb_protocol       = "tcp"
  }

  listener {
    instance_port     = 32000
    instance_protocol = "tcp"
    lb_port           = 3000
    lb_protocol       = "tcp"
  }

  listener {
    instance_port     = 30000
    instance_protocol = "tcp"
    lb_port           = 8080
    lb_protocol       = "tcp"
  }

  security_groups = [aws_security_group.permitir_ssh_http_nodes.id]
  subnets = [aws_subnet.Public_subnet.id]
  instances                   = data.aws_instances.k3s_workers.ids
  cross_zone_load_balancing   = true
  idle_timeout                = 400
  connection_draining         = true
  connection_draining_timeout = 400

  tags = {
    Name = "k3s-elb"
  }
}
