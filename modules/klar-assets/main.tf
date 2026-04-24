data "aws_eks_cluster" "current-cluster" {
  name = jsondecode(data.aws_s3_bucket_object.eks-cluster-state.body).cluster_name
}

data "aws_eks_cluster_auth" "cluster-auth" {
  name = jsondecode(data.aws_s3_bucket_object.eks-cluster-state.body).cluster_name
}

data "aws_s3_bucket_object" "eks-cluster-state" {
  bucket = "klar-${var.environment}-terraform-exports"
  key    = "DevOps-infra/eks-cluster.json"
}

#### Resources #####

resource "kubernetes_namespace" "namespace" {
  metadata {
    name = var.namespace
  }
}

data "aws_kms_secrets" "secret" {
  secret {
    name    = "OKTA_OIDC_CLIENT_ID"
    payload = var.OKTA_OIDC_CLIENT_ID
  }
   secret {
    name    = "OKTA_OIDC_CLIENT_SECRET"
    payload = var.OKTA_OIDC_CLIENT_SECRET
  }
   secret {
    name    = "OKTA_API_TOKEN"
    payload = var.OKTA_API_TOKEN
  }
   secret {
    name    = "JC_API_KEY"
    payload = var.JC_API_KEY
  }
   secret {
    name    = "AUTH_PASSWORD"
    payload = var.AUTH_PASSWORD
  }
     secret {
    name    = "OPENAI_API_KEY"
    payload = var.OPENAI_API_KEY
  }
     secret {
    name    = "OKTA_OIDC_ISSUER"
    payload = var.OKTA_OIDC_ISSUER
  }
    secret {
    name    = "OKTA_ALLOWED_DOMAINS"
    payload = var.OKTA_ALLOWED_DOMAINS
  }
    secret {
    name    = "SLACK_WEBHOOK_URL"
    payload = var.SLACK_WEBHOOK_URL
  }

}

resource "kubectl_manifest" "secret" {
  yaml_body = <<-YAML
      apiVersion: v1
      kind: Secret
      metadata:
        name: klar-assets-secrets
        namespace: klar-assets
      type: Opaque
      stringData:
        OKTA_OIDC_CLIENT_ID : ${data.aws_kms_secrets.secret.plaintext["OKTA_OIDC_CLIENT_ID"]}
        OKTA_OIDC_CLIENT_SECRET: ${data.aws_kms_secrets.secret.plaintext["OKTA_OIDC_CLIENT_SECRET"]}
        OKTA_API_TOKEN: ${data.aws_kms_secrets.secret.plaintext["OKTA_API_TOKEN"]}
        JC_API_KEY: ${data.aws_kms_secrets.secret.plaintext["JC_API_KEY"]}
        AUTH_PASSWORD: ${data.aws_kms_secrets.secret.plaintext["AUTH_PASSWORD"]}
        OPENAI_API_KEY: ${data.aws_kms_secrets.secret.plaintext["OPENAI_API_KEY"]}
        SLACK_WEBHOOK_URL: ${data.aws_kms_secrets.secret.plaintext["SLACK_WEBHOOK_URL"]}
        OKTA_OIDC_ISSUER: ${data.aws_kms_secrets.secret.plaintext["OKTA_OIDC_ISSUER"]}
        OKTA_ALLOWED_DOMAINS: ${data.aws_kms_secrets.secret.plaintext["OKTA_ALLOWED_DOMAINS"]}
      YAML

  sensitive_fields = ["stringData"]
  depends_on = [kubernetes_namespace.namespace]
}


data "kubectl_filename_list" "manifests" {
    pattern = "./kubernetes/*.yaml"
}

resource "kubectl_manifest" "klar-assets" {
    count = length(data.kubectl_filename_list.manifests.matches)
    yaml_body = file(element(data.kubectl_filename_list.manifests.matches, count.index))

    depends_on = [kubernetes_namespace.namespace]
}