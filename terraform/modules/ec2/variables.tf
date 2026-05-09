variable "name" {
  description = "Name tag for the EC2 instance (e.g. pulse-staging)"
  type        = string
}

variable "ami" {
  description = "AMI ID to use"
  type        = string
  default     = "ami-0a628e1e89aaedf80"  # Ubuntu 24.04 eu-central-1
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.micro"
}

variable "key_name" {
  description = "Name of the SSH key pair to attach"
  type        = string
}

variable "security_group_id" {
  description = "ID of the security group to attach"
  type        = string
}