output "endpoint" {
  description = "Endpoint de la instancia RDS"
  value       = aws_db_instance.main.address
}

output "port" {
  description = "Puerto de PostgreSQL"
  value       = aws_db_instance.main.port
}

output "db_name" {
  description = "Nombre de la base de datos"
  value       = aws_db_instance.main.db_name
}

output "security_group_id" {
  description = "Security group de la base de datos"
  value       = aws_security_group.db.id
}
