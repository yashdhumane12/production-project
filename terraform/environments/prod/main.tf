terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.40" }
  }
  backend "s3" {
    bucket         = "taskmaster-tfstate"
    key            = "prod/terraform.tfstate"
    region         = "ap-south-1"
    encrypt        = true
    dynamodb_table = "terraform-state-lock"
  }
}

provider "aws" {
  region = var.aws_region
  default_tags { tags = local.tags }
}

locals {
  env  = "prod"
  tags = { Project = "taskmaster", Environment = local.env, ManagedBy = "Terraform" }
}

module "vpc" {
  source               = "../../modules/vpc"
  project              = "taskmaster"
  environment          = local.env
  vpc_cidr             = "10.0.0.0/16"
  public_subnet_cidrs  = ["10.0.1.0/24", "10.0.2.0/24"]
  private_subnet_cidrs = ["10.0.10.0/24", "10.0.11.0/24"]
  availability_zones   = ["${var.aws_region}a", "${var.aws_region}b"]
  common_tags          = local.tags
}

module "ec2" {
  source         = "../../modules/ec2"
  project        = "taskmaster"
  environment    = local.env
  vpc_id         = module.vpc.vpc_id
  subnet_ids     = module.vpc.private_subnet_ids
  ami_id         = var.ami_id
  instance_type  = "t3.small"
  instance_count = 2
  key_name       = var.key_name
  common_tags    = local.tags
}

output "vpc_id"           { value = module.vpc.vpc_id }
output "ec2_private_ips"  { value = module.ec2.private_ips }
