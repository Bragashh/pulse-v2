output "key_name" {
  description = "Name of the key pair (for use in EC2 modules)"
  value       = aws_key_pair.pulse_key.key_name
}

output "security_group_id" {
  description = "ID of the security group (for use in EC2 modules)"
  value       = aws_security_group.pulse_sg.id
}