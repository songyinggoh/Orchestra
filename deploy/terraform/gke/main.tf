# Orchestra GKE Terraform module
# Module: terraform-google-modules/kubernetes-engine/google ~> 35.0
# Usage: terraform init && terraform apply -var="project_id=my-gcp-project"

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "dev"
}

module "vpc" {
  source  = "terraform-google-modules/network/google"
  version = "~> 9.0"

  project_id   = var.project_id
  network_name = "orchestra-${var.environment}"
  routing_mode = "GLOBAL"

  subnets = [{
    subnet_name   = "orchestra-nodes"
    subnet_ip     = "10.0.0.0/20"
    subnet_region = var.region
  }]

  secondary_ranges = {
    orchestra-nodes = [
      { range_name = "pods",     ip_cidr_range = "10.1.0.0/16" },
      { range_name = "services", ip_cidr_range = "10.2.0.0/20" },
    ]
  }
}

module "gke" {
  source  = "terraform-google-modules/kubernetes-engine/google"
  version = "~> 35.0"

  project_id = var.project_id
  name       = "orchestra-${var.environment}"
  region     = var.region

  kubernetes_version = "1.31"
  release_channel    = "REGULAR"

  network           = module.vpc.network_name
  subnetwork        = module.vpc.subnets_names[0]
  ip_range_pods     = "pods"
  ip_range_services = "services"

  # Workload Identity — replaces per-node service accounts
  identity_namespace = "${var.project_id}.svc.id.goog"

  node_pools = [
    {
      name         = "system"
      machine_type = "e2-standard-2"
      min_count    = 2
      max_count    = 4
      auto_upgrade = true
    },
    {
      name           = "agent-workers"
      machine_type   = "c2-standard-4"
      min_count      = 1
      max_count      = 20
      auto_upgrade   = true
      # GKE native gVisor support — no DaemonSet installer needed
      sandbox_config = [{ sandbox_type = "gvisor" }]
    }
  ]

  node_pools_labels = {
    agent-workers = {
      "orchestra.dev/role"    = "agent"
      "orchestra.dev/sandbox" = "gvisor"
    }
  }

  node_pools_taints = {
    agent-workers = [{
      key    = "orchestra.dev/agent-only"
      value  = "true"
      effect = "NO_SCHEDULE"
    }]
  }
}

output "cluster_name" {
  value = module.gke.name
}

output "kubeconfig_command" {
  value = "gcloud container clusters get-credentials ${module.gke.name} --region ${var.region} --project ${var.project_id}"
}
