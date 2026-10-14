# Provider configurado para PLAN OFFLINE (local-only, sin credenciales reales).
# Los flags skip_* y las credenciales mock permiten `terraform plan` sin cuenta AWS.
# Para un `apply` real: eliminar access_key/secret_key/skip_* y usar `aws_profile`.
provider "aws" {
  region = var.aws_region

  access_key                  = "mock"
  secret_key                  = "mock"
  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
