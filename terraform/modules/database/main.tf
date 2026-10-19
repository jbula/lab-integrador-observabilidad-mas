# ════════════════════════════════════════════════════════════════════════════
# RDS PostgreSQL para data-service (Lab 4, Modulo A)
# Dimensionado para la capa gratuita: db.t3.micro, 20 GB, sin multi-AZ.
# ════════════════════════════════════════════════════════════════════════════

resource "aws_db_subnet_group" "main" {
  name       = "${var.name_prefix}-db"
  subnet_ids = var.subnet_ids
  tags       = merge(var.tags, { Name = "${var.name_prefix}-db-subnets" })
}

# El acceso a la base queda restringido al security group de las tareas ECS:
# la instancia no es accesible desde internet.
resource "aws_security_group" "db" {
  name        = "${var.name_prefix}-db-sg"
  description = "Acceso a PostgreSQL solo desde las tareas ECS"
  vpc_id      = var.vpc_id
  tags        = merge(var.tags, { Name = "${var.name_prefix}-db-sg" })

  ingress {
    description     = "PostgreSQL desde las tareas ECS"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.ecs_sg_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "main" {
  identifier     = "${var.name_prefix}-analytics"
  engine         = "postgres"
  engine_version = "16.15"

  instance_class        = var.instance_class    # db.t3.micro: capa gratuita
  allocated_storage     = var.allocated_storage # 20 GB: capa gratuita
  storage_type          = "gp2"
  max_allocated_storage = 0 # sin autoescalado: evita sobrepasar la capa gratuita

  db_name  = var.db_name
  username = var.db_username
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  multi_az                = false # capa gratuita: una sola zona
  backup_retention_period = 0     # sin backups: evita costo de almacenamiento
  skip_final_snapshot     = true  # laboratorio: permite destroy inmediato
  deletion_protection     = false
  apply_immediately       = true

  storage_encrypted = true
  tags              = merge(var.tags, { Name = "${var.name_prefix}-analytics-db" })
}
