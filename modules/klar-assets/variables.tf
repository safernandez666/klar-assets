variable "environment" {
  type = string
}

variable "region" {
  type    = string
  default = "us-east-2"
}

variable "namespace" {
  type    = string
  default = ""
}

variable "OKTA_OIDC_CLIENT_ID" {
  type    = string
  default = ""
}

variable "OKTA_OIDC_CLIENT_SECRET" {
  type    = string
  default = ""
}

variable "OKTA_API_TOKEN" {
  type    = string
  default = ""
}

variable "JC_API_KEY" {
  type    = string
  default = ""
}

variable "AUTH_PASSWORD" {
  type    = string
  default = ""
}

variable "OPENAI_API_KEY" {
  type    = string
  default = ""
}

variable "SLACK_WEBHOOK_URL" {
  type    = string
  default = ""
}

variable "OKTA_OIDC_ISSUER" {
  type    = string
  default = ""
}

variable "OKTA_ALLOWED_DOMAINS" {
  type    = string
  default = ""
}


