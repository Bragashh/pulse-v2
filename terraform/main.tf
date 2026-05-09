terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "eu-central-1"
}

module "networking" {
  source = "./modules/networking"
}

module "staging" {
  source            = "./modules/ec2"
  name              = "pulse-v2-staging"
  key_name          = module.networking.key_name
  security_group_id = module.networking.security_group_id
}

module "production" {
  source            = "./modules/ec2"
  name              = "pulse-v2-production"
  key_name          = module.networking.key_name
  security_group_id = module.networking.security_group_id
}