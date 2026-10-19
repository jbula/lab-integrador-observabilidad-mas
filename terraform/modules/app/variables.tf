variable "name_prefix"        { type = string }
variable "vpc_id"             { type = string }
variable "aws_region"         { type = string }
variable "account_id"         { type = string }
variable "image_tag"          { type = string }
variable "cluster_id"         { type = string }
variable "namespace_arn"      { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "public_subnet_ids"  { type = list(string) }
variable "alb_sg_id"          { type = string }
variable "ecs_sg_id"          { type = string }
variable "execution_role_arn" { type = string }
variable "task_role_arn"      { type = string }
variable "ecr_urls"           { type = map(string) }
variable "tags"               { type = map(string) }

variable "rds_endpoint" {
  type = string
}

variable "rds_db_name" {
  type = string
}

variable "db_password" {
  type      = string
  sensitive = true
}
