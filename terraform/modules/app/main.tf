locals {
  services = {
    service-a = { port = 8000, db = "ordersdb" }
    service-b = { port = 8001, db = "inventorydb" }
  }
  secret_arn_prefix = "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:${var.name_prefix}"
}

resource "aws_cloudwatch_log_group" "svc" {
  for_each          = local.services
  name              = "/${var.name_prefix}/${each.key}"
  retention_in_days = 7
  tags              = var.tags
}

# Task definition con 3 contenedores: servicio + collector (sidecar) + postgres (sidecar)
resource "aws_ecs_task_definition" "svc" {
  for_each                 = local.services
  family                   = "${var.name_prefix}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"

  # Las imagenes se construyen en Apple Silicon (arm64). Fargate soporta ARM64
  # de forma nativa, lo que evita recompilar con emulacion para x86_64.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = each.key
      image     = "${var.ecr_urls[each.key]}:${var.image_tag}"
      essential = true
      portMappings = [{ containerPort = each.value.port, protocol = "tcp", name = each.key }]
      environment = [
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4317" },
        { name = "ENVIRONMENT", value = "production" },
        { name = "CLOUD_PROVIDER", value = "aws" },
        { name = "DATABASE_URL", value = "postgresql://app:secret@localhost:5432/${each.value.db}" },
        { name = "DATA_SERVICE_URL", value = "http://data-service:8002" }
      ]
      dependsOn = [
        { containerName = "otel-collector", condition = "START" },
        { containerName = "postgres", condition = "HEALTHY" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.svc[each.key].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = each.key
        }
      }
    },
    {
      name      = "otel-collector"
      image     = "${var.ecr_urls["otel-collector"]}:${var.image_tag}"
      essential = true
      command   = ["--config=/etc/otel/collector-config.aws.yaml"]
      environment = [
        { name = "ENVIRONMENT", value = "production" },
        { name = "AWS_REGION", value = var.aws_region }
      ]
      # Sin healthCheck: la imagen del collector no incluye wget ni curl, por lo
      # que cualquier comprobacion basada en ellos quedaria siempre en UNKNOWN.
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.svc[each.key].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "otel-collector"
        }
      }
    },
    {
      name      = "postgres"
      image     = "postgres:16-alpine"
      essential = true
      environment = [
        { name = "POSTGRES_USER", value = "app" },
        { name = "POSTGRES_DB", value = each.value.db }
      ]
      secrets = [
        { name = "POSTGRES_PASSWORD", valueFrom = "${local.secret_arn_prefix}/db-password" }
      ]
      healthCheck = {
        command     = ["CMD-SHELL", "pg_isready -U app -d ${each.value.db}"]
        interval    = 10
        timeout     = 5
        retries     = 5
        startPeriod = 20
      }
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.svc[each.key].name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "postgres"
        }
      }
    }
  ])
  tags = var.tags
}

# ALB público (restringido por SG a la IP del operador)
resource "aws_lb" "main" {
  name               = "${var.name_prefix}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [var.alb_sg_id]
  subnets            = var.public_subnet_ids
  tags               = var.tags
}

resource "aws_lb_target_group" "service_a" {
  name        = "${var.name_prefix}-svc-a"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"
  health_check {
    path    = "/health"
    matcher = "200"
  }
  tags = var.tags
}


resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.service_a.arn
  }
}

resource "aws_ecs_service" "svc" {
  for_each        = local.services
  name            = "${var.name_prefix}-${each.key}"
  cluster         = var.cluster_id
  task_definition = aws_ecs_task_definition.svc[each.key].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  # Subnets publicas con IP publica: permite descargar imagenes de ECR sin
  # NAT Gateway (que costaria ~0.045 USD/h). El acceso entrante sigue
  # restringido por el security group (solo ALB y trafico entre tareas).
  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = true
  }

  service_connect_configuration {
    enabled   = true
    namespace = var.namespace_arn
    service {
      port_name      = each.key
      discovery_name = each.key
      client_alias {
        port     = each.value.port
        dns_name = each.key
      }
    }
  }

  dynamic "load_balancer" {
    for_each = each.key == "service-a" ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.service_a.arn
      container_name   = "service-a"
      container_port   = 8000
    }
  }
  tags = var.tags
}

# ── data-service (Lab 4, Modulo A): usa RDS en lugar de postgres sidecar ────
resource "aws_cloudwatch_log_group" "data_service" {
  name              = "/${var.name_prefix}/data-service"
  retention_in_days = 7
  tags              = var.tags
}

resource "aws_ecs_task_definition" "data_service" {
  family                   = "${var.name_prefix}-data-service"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"

  # Las imagenes se construyen en Apple Silicon (arm64). Fargate soporta ARM64
  # de forma nativa, lo que evita recompilar con emulacion para x86_64.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name         = "data-service"
      image        = "${var.ecr_urls["data-service"]}:${var.image_tag}"
      essential    = true
      portMappings = [{ containerPort = 8002, protocol = "tcp", name = "data-service" }]
      environment = [
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4317" },
        { name = "ENVIRONMENT", value = "production" },
        { name = "CLOUD_PROVIDER", value = "aws" },
        { name = "DB_HOST", value = var.rds_endpoint },
        { name = "DB_NAME", value = var.rds_db_name },
        { name = "DATABASE_URL", value = "postgresql://app:${var.db_password}@${var.rds_endpoint}:5432/${var.rds_db_name}" },
      ]
      dependsOn = [{ containerName = "otel-collector", condition = "START" }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.data_service.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "data-service"
        }
      }
    },
    {
      name      = "otel-collector"
      image     = "${var.ecr_urls["otel-collector"]}:${var.image_tag}"
      essential = true
      command   = ["--config=/etc/otel/collector-config.aws.yaml"]
      environment = [
        { name = "ENVIRONMENT", value = "production" },
        { name = "AWS_REGION", value = var.aws_region },
      ]
      # Sin healthCheck: la imagen del collector no incluye wget ni curl, por lo
      # que cualquier comprobacion basada en ellos quedaria siempre en UNKNOWN.
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.data_service.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "otel-collector"
        }
      }
    }
  ])
  tags = var.tags
}

resource "aws_ecs_service" "data_service" {
  name            = "${var.name_prefix}-data-service"
  cluster         = var.cluster_id
  task_definition = aws_ecs_task_definition.data_service.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  # Subnets publicas con IP publica: permite descargar imagenes de ECR sin
  # NAT Gateway (que costaria ~0.045 USD/h). El acceso entrante sigue
  # restringido por el security group (solo ALB y trafico entre tareas).
  network_configuration {
    subnets          = var.public_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = true
  }

  service_connect_configuration {
    enabled   = true
    namespace = var.namespace_arn
    service {
      port_name      = "data-service"
      discovery_name = "data-service"
      client_alias {
        port     = 8002
        dns_name = "data-service"
      }
    }
  }
  tags = var.tags
}
