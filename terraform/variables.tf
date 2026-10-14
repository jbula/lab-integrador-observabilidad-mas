variable "aws_region" {
  description = "Región AWS objetivo"
  type        = string
  default     = "us-east-1"
}

variable "account_id" {
  description = "ID de cuenta AWS (placeholder en local; en apply real usar data.aws_caller_identity)"
  type        = string
  default     = "000000000000"
}

variable "project" {
  description = "Prefijo de proyecto para nombres y tags"
  type        = string
  default     = "otel-lab"
}

variable "environment" {
  description = "Ambiente lógico"
  type        = string
  default     = "lab"
}

variable "vpc_cidr" {
  description = "CIDR de la VPC"
  type        = string
  default     = "10.20.0.0/16"
}

variable "azs" {
  description = "Availability Zones (estáticas para plan offline)"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "allowed_cidr" {
  description = "IP/CIDR del operador con acceso a Jaeger/Grafana/Prometheus"
  type        = string
  default     = "203.0.113.10/32"
}

variable "image_tag" {
  description = "Tag de las imágenes de contenedor (no 'latest')"
  type        = string
  default     = "1.0.0"
}

variable "db_password" {
  description = "Password de PostgreSQL (en apply real va a Secrets Manager)"
  type        = string
  default     = "changeme-in-secrets-manager"
  sensitive   = true
}
