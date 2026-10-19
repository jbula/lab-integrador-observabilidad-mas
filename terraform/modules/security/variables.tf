variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "flow_logs_retention" {
  type    = number
  default = 7
}

variable "enable_flow_logs" {
  type    = bool
  default = true
}

variable "tags" {
  type = map(string)
}
