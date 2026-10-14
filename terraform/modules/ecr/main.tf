resource "aws_ecr_repository" "this" {
  for_each             = toset(var.repos)
  name                 = "${var.name_prefix}/${each.value}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
  tags = merge(var.tags, { Name = "${var.name_prefix}-${each.value}" })
}
