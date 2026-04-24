terraform {
  required_providers {
     kubectl = {
      source  = "gavinbunney/kubectl"
      version = ">= 1.7.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = ">= 3.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = ">= 2.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.16"
    }
  }
  required_version = ">= 1.2.9"
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.current-cluster.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.current-cluster.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.cluster-auth.token
}

provider "kubectl" {
  host                   = jsondecode(data.aws_s3_bucket_object.eks-cluster-state.body).endpoint
  cluster_ca_certificate = base64decode(jsondecode(data.aws_s3_bucket_object.eks-cluster-state.body).cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.cluster-auth.token
  load_config_file       = false
}

terraform {
  backend "s3" {}
}

provider "aws" {
  region = var.region
}