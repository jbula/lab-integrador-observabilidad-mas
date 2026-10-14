output "backend_services" {
  value = { for k, s in aws_ecs_service.backend : k => s.name }
}
