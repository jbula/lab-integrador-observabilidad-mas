locals {
  backends = {
    jaeger     = { image = "jaegertracing/all-in-one:1.58", port = 16686, cpu = 256, mem = 512 }
    prometheus = { image = "prom/prometheus:v2.52.0",        port = 9090,  cpu = 256, mem = 512 }
    grafana    = { image = "grafana/grafana:10.4.0",         port = 3000,  cpu = 256, mem = 512 }
  }
}

resource "aws_cloudwatch_log_group" "backend" {
  for_each          = local.backends
  name              = "/${var.name_prefix}/${each.key}"
  retention_in_days = 7
  tags              = var.tags
}

resource "aws_service_discovery_service" "backend" {
  for_each = local.backends
  name     = each.key

  dns_config {
    namespace_id = var.namespace_id
    dns_records {
      type = "A"
      ttl  = 10
    }
    routing_policy = "MULTIVALUE"
  }
  health_check_custom_config {
    failure_threshold = 1
  }
  tags = var.tags
}

resource "aws_ecs_task_definition" "backend" {
  for_each                 = local.backends
  family                   = "${var.name_prefix}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }
  cpu                      = each.value.cpu
  memory                   = each.value.mem
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = each.key
      image     = each.value.image
      essential = true
      portMappings = [
        { containerPort = each.value.port, protocol = "tcp" }
      ]
      environment = each.key == "jaeger" ? [
        { name = "COLLECTOR_OTLP_ENABLED", value = "true" }
      ] : []
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.backend[each.key].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = each.key
        }
      }
    }
  ])
  tags = var.tags
}

resource "aws_ecs_service" "backend" {
  for_each        = local.backends
  name            = "${var.name_prefix}-${each.key}"
  cluster         = var.cluster_id
  task_definition = aws_ecs_task_definition.backend[each.key].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = true
  }

  service_registries {
    registry_arn = aws_service_discovery_service.backend[each.key].arn
  }
  tags = var.tags
}
