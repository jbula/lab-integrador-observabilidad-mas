variable "aws_region" {
  description = "Región AWS objetivo"
  type        = string
  default     = "us-east-2"
}

variable "account_id" {
  description = "ID de cuenta AWS. En modo offline se usa este valor; en apply real se resuelve con data.aws_caller_identity."
  type        = string
  default     = "000000000000"
}

variable "offline_plan" {
  description = "true = plan sin credenciales (credenciales simuladas y validaciones omitidas). false = apply real con perfil."
  type        = bool
  default     = true
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
  default     = ["us-east-2a", "us-east-2b"]
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

variable "aws_profile" {
  description = "Perfil del AWS CLI para apply real. Vacio en modo offline."
  type        = string
  default     = ""
}

variable "enable_flow_logs" {
  description = "Habilita VPC Flow Logs hacia CloudWatch"
  type        = bool
  default     = true
}

variable "flow_logs_retention" {
  description = "Dias de retencion de los Flow Logs"
  type        = number
  default     = 7
}

variable "db_instance_class" {
  description = "Clase de instancia RDS (db.t3.micro = capa gratuita)"
  type        = string
  default     = "db.t3.micro"
}
