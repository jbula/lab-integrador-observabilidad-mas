output "flow_logs_log_group" {
  description = "Log group de CloudWatch con los VPC Flow Logs"
  value       = var.enable_flow_logs ? aws_cloudwatch_log_group.flow_logs[0].name : null
}

output "flow_log_id" {
  description = "ID del flow log de la VPC"
  value       = var.enable_flow_logs ? aws_flow_log.vpc[0].id : null
}
