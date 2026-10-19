output "vpc_id" {
  description = "ID de la VPC"
  value       = module.network.vpc_id
}

output "alb_dns_name" {
  description = "DNS del ALB público (Jaeger/Grafana/service-a)"
  value       = module.app.alb_dns_name
}

output "ecr_repository_urls" {
  description = "URLs de los repositorios ECR"
  value       = module.ecr.repository_urls
}

output "ecs_cluster_name" {
  description = "Nombre del cluster ECS"
  value       = aws_ecs_cluster.main.name
}

output "flow_logs_log_group" {
  description = "Log group de los VPC Flow Logs"
  value       = module.security.flow_logs_log_group
}

output "rds_endpoint" {
  description = "Endpoint de la base de datos de analitica"
  value       = module.database.endpoint
}
