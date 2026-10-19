# ════════════════════════════════════════════════════════════════════════════
# Modulo de observabilidad de seguridad (Lab 4, Modulo C)
#
# VPC Flow Logs hacia CloudWatch Logs para analizar el trafico Norte-Sur y
# Este-Oeste entre servicios.
#
# NOTA: AWS Security Hub, GuardDuty, Inspector y Config estan denegados por una
# Service Control Policy de la organizacion propietaria de esta cuenta, por lo
# que no pueden declararse aqui. La observabilidad de vulnerabilidades se cubre
# con el escaneo de imagenes de ECR (modulo ecr) y con Trivy en local.
# ════════════════════════════════════════════════════════════════════════════

resource "aws_cloudwatch_log_group" "flow_logs" {
  count             = var.enable_flow_logs ? 1 : 0
  name              = "/${var.name_prefix}/vpc-flow-logs"
  retention_in_days = var.flow_logs_retention # retencion corta: contiene el costo de ingesta
  tags              = var.tags
}

data "aws_iam_policy_document" "flow_logs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "flow_logs_publish" {
  statement {
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
    ]
    resources = ["*"] # requerido por el servicio de Flow Logs
  }
}

resource "aws_iam_role" "flow_logs" {
  count              = var.enable_flow_logs ? 1 : 0
  name               = "${var.name_prefix}-flow-logs"
  assume_role_policy = data.aws_iam_policy_document.flow_logs_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "flow_logs" {
  count  = var.enable_flow_logs ? 1 : 0
  name   = "${var.name_prefix}-flow-logs-publish"
  role   = aws_iam_role.flow_logs[0].id
  policy = data.aws_iam_policy_document.flow_logs_publish.json
}

resource "aws_flow_log" "vpc" {
  count                    = var.enable_flow_logs ? 1 : 0
  vpc_id                   = var.vpc_id
  traffic_type             = "ALL"
  log_destination_type     = "cloud-watch-logs"
  log_destination          = aws_cloudwatch_log_group.flow_logs[0].arn
  iam_role_arn             = aws_iam_role.flow_logs[0].arn
  max_aggregation_interval = 60 # granularidad fina para el analisis N-S / E-W
  tags                     = merge(var.tags, { Name = "${var.name_prefix}-vpc-flow-log" })
}
