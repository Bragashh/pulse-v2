# EC2 module — one Ubuntu instance with a permanent Elastic IP.

resource "aws_instance" "this" {
  ami                    = var.ami
  instance_type          = var.instance_type
  key_name               = var.key_name
  vpc_security_group_ids = [var.security_group_id]

  tags = {
    Name = var.name
  }
}

resource "aws_eip" "this" {
  instance = aws_instance.this.id
  domain   = "vpc"

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = "${var.name}-eip"
  }
}