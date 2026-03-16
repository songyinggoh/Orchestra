# Orchestra EKS Terraform module
# Module: terraform-aws-modules/eks/aws ~> 20.0
# Usage: terraform init && terraform apply -var="environment=prod"

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

data "aws_availability_zones" "available" {}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "orchestra-${var.environment}"
  cidr = "10.0.0.0/16"

  azs             = slice(data.aws_availability_zones.available.names, 0, 3)
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = var.environment != "prod"

  tags = {
    "kubernetes.io/cluster/orchestra-${var.environment}" = "shared"
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = "orchestra-${var.environment}"
  cluster_version = "1.31"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Set false for production (access via VPN/bastion only)
  cluster_endpoint_public_access = var.environment != "prod"

  cluster_addons = {
    coredns    = { most_recent = true }
    kube-proxy = { most_recent = true }
    vpc-cni    = { most_recent = true }
  }

  eks_managed_node_groups = {
    # System workloads (control plane components, KEDA, OTel collector)
    system = {
      instance_types = ["t3.medium"]
      min_size       = 2
      max_size       = 4
      desired_size   = 2
      labels = {
        "orchestra.dev/role" = "system"
      }
    }

    # Standard agent workers
    agent-workers = {
      instance_types = ["c5.xlarge"]
      min_size       = 1
      max_size       = 20
      desired_size   = 2
      labels = {
        "orchestra.dev/role" = "agent"
      }
      taints = [{
        key    = "orchestra.dev/agent-only"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]
    }

    # Secure agent workers — gVisor installed via DaemonSet post-provisioning
    # See: deploy/gvisor-installer-daemonset.yaml
    secure-workers = {
      instance_types = ["c5.xlarge"]
      min_size       = 0
      max_size       = 10
      desired_size   = 1
      labels = {
        "orchestra.dev/role"    = "secure-agent"
        "orchestra.dev/sandbox" = "gvisor"
      }
    }
  }

  # Enable IRSA for KEDA, OTel Collector, and other AWS-integrated components
  enable_irsa = true

  tags = {
    Environment = var.environment
    Project     = "orchestra"
    ManagedBy   = "terraform"
  }
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value     = module.eks.cluster_endpoint
  sensitive = true
}

output "kubeconfig_command" {
  value = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.region}"
}
