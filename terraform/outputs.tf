output "staging_ip" {
  description = "Public IP of the staging EC2"
  value       = module.staging.public_ip
}

output "production_ip" {
  description = "Public IP of the production EC2"
  value       = module.production.public_ip
}