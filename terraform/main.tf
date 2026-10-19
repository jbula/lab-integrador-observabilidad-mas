locals {
  name_prefix = "${var.project}-${var.environment}"
  common_tags = {
    Project     = var.project
    Environment = var.environment
  }
}

module "network" {
  source       = "./modules/network"
  name_prefix  = local.name_prefix
  vpc_cidr     = var.vpc_cidr
  azs          = var.azs
  allowed_cidr = var.allowed_cidr
  tags         = local.common_tags
}

module "ecr" {
  source      = "./modules/ecr"
  name_prefix = local.name_prefix
  repos       = ["service-a", "service-b", "data-service", "otel-collector"]
  tags        = local.common_tags
}

module "iam" {
  source      = "./modules/iam"
  name_prefix = local.name_prefix
  aws_region  = var.aws_region
  account_id  = local.effective_account_id
  tags        = local.common_tags
}

# Cluster ECS y namespace Cloud Map en el root → compartidos por observability y app
# (evita dependencia circular entre módulos).
resource "aws_ecs_cluster" "main" {
  name = local.name_prefix
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
  tags = local.common_tags
}

resource "aws_service_discovery_private_dns_namespace" "main" {
  name        = "${var.project}.local"
  description = "Service Connect namespace para ${local.name_prefix}"
  vpc         = module.network.vpc_id
  tags        = local.common_tags
}

module "observability" {
  source             = "./modules/observability"
  name_prefix        = local.name_prefix
  aws_region         = var.aws_region
  cluster_id         = aws_ecs_cluster.main.id
  namespace_id       = aws_service_discovery_private_dns_namespace.main.id
  private_subnet_ids = module.network.private_subnet_ids
  public_subnet_ids  = module.network.public_subnet_ids
  ecs_sg_id          = module.network.ecs_sg_id
  execution_role_arn = module.iam.execution_role_arn
  task_role_arn      = module.iam.task_role_arn
  tags               = local.common_tags
}

module "app" {
  source             = "./modules/app"
  vpc_id             = module.network.vpc_id
  name_prefix        = local.name_prefix
  aws_region         = var.aws_region
  account_id         = local.effective_account_id
  image_tag          = var.image_tag
  cluster_id         = aws_ecs_cluster.main.id
  namespace_arn      = aws_service_discovery_private_dns_namespace.main.arn
  private_subnet_ids = module.network.private_subnet_ids
  public_subnet_ids  = module.network.public_subnet_ids
  alb_sg_id          = module.network.alb_sg_id
  ecs_sg_id          = module.network.ecs_sg_id
  execution_role_arn = module.iam.execution_role_arn
  task_role_arn      = module.iam.task_role_arn
  ecr_urls           = module.ecr.repository_urls
  rds_endpoint       = module.database.endpoint
  rds_db_name        = module.database.db_name
  db_password        = var.db_password
  tags               = local.common_tags
}

# ── Observabilidad de seguridad: VPC Flow Logs (Lab 4, Modulo C) ────────────
module "security" {
  source              = "./modules/security"
  name_prefix         = local.name_prefix
  vpc_id              = module.network.vpc_id
  enable_flow_logs    = var.enable_flow_logs
  flow_logs_retention = var.flow_logs_retention
  tags                = local.common_tags
}

# ── RDS PostgreSQL para data-service (Lab 4, Modulo A) ──────────────────────
module "database" {
  source         = "./modules/database"
  name_prefix    = local.name_prefix
  vpc_id         = module.network.vpc_id
  subnet_ids     = module.network.private_subnet_ids
  ecs_sg_id      = module.network.ecs_sg_id
  db_password    = var.db_password
  instance_class = var.db_instance_class
  tags           = local.common_tags
}
