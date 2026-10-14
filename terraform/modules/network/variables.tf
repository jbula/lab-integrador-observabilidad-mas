variable "name_prefix" { type = string }
variable "vpc_cidr"    { type = string }
variable "azs"         { type = list(string) }
variable "allowed_cidr" { type = string }
variable "tags"        { type = map(string) }
