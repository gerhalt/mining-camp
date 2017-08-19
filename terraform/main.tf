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
    from_port   = "${var.minecraft["port"]}"
    to_port     = "${var.minecraft["port"]}"
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

# TODO: Set up Elastic IP

# AMI to use for our instances
data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-xenial-16.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["099720109477"] # Canonical
}


# Launch configuration
# We'll use this to easy turn on and off our server without having to remake
# our entire instance configuration every time.


resource "aws_launch_configuration" "minecraft" {
  name          = "minecraft-conf"
  image_id      = "${data.aws_ami.ubuntu.id}"
  instance_type = "i3.large" 
  spot_price    = "${var.max_spot_price}"
  ebs_optimized = false 

  iam_instance_profile = "${aws_iam_role.minecraft_role.name}"
  security_groups      = ["${aws_security_group.default.id}"]
}
























