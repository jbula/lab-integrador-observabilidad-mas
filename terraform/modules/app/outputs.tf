output "alb_dns_name" { value = aws_lb.main.dns_name }
output "service_names" { value = { for k, s in aws_ecs_service.svc : k => s.name } }
