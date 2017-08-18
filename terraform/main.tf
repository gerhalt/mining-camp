# Provider and access details
provider "aws" {
  profile = "minecraft"
  region  = "${var.aws_region}"
}

# Create a VPC for our instances
resource "aws_vpc" "default" {
  cidr_block = "10.0.0.0/16"
}

# Create a gateway for our VPC
resource "aws_internet_gateway" "default" {
  vpc_id = "${aws_vpc.default.id}"
}

# Security group that allows SSH, Web Traffic, and a special port for our
# Minecraft server
resource "aws_security_group" "default" {
  name        = "minecraft"
  description = "Security group for standalone MC server"
  vpc_id      = "${aws_vpc.default.id}"

  # HTTP
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # SSH
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Minecraft
  ingress {
    from_port   = "${var.minecraft_port}"
    to_port     = "${var.minecraft_port}"
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Outbound
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
