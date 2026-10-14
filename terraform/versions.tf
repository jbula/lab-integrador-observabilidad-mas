terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Backend local por defecto (modo local-only, sin cuenta AWS).
  # Para producción, migrar a S3 + DynamoDB con `terraform init -migrate-state`:
  # backend "s3" {
  #   bucket         = "otel-lab-tfstate"
  #   key            = "otel-lab/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "otel-lab-tflock"
  #   encrypt        = true
  # }
}
