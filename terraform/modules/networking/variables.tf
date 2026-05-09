variable "key_name" {
  description = "Name for the SSH key pair in AWS"
  type        = string
  default     = "pulse-v2-key"
}

variable "public_key_path" {
  description = "Path to the SSH public key file on the local machine"
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}

variable "security_group_name" {
  description = "Name for the security group"
  type        = string
  default     = "pulse-v2-sg"
}