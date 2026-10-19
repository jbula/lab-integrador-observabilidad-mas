# Provider con doble modo:
#  - offline_plan = true  -> credenciales simuladas, validaciones omitidas (plan sin cuenta AWS)
#  - offline_plan = false -> usa el perfil del AWS CLI indicado en var.aws_profile (apply real)
provider "aws" {
  region  = var.aws_region
  profile = var.offline_plan ? null : (var.aws_profile != "" ? var.aws_profile : null)

  access_key = var.offline_plan ? "mock" : null
  secret_key = var.offline_plan ? "mock" : null

  skip_credentials_validation = var.offline_plan
  skip_requesting_account_id  = var.offline_plan
  skip_metadata_api_check     = var.offline_plan
  skip_region_validation      = var.offline_plan

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# En apply real se resuelve el account_id desde las credenciales; en offline se usa la variable.
data "aws_caller_identity" "current" {
  count = var.offline_plan ? 0 : 1
}

locals {
  effective_account_id = var.offline_plan ? var.account_id : data.aws_caller_identity.current[0].account_id
}
