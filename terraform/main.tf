# Provider and access details
provider "aws" {
  profile = "minecraft"
  region  = "${var.aws_region}"
}

# Create a VPC for our instances
resource "aws_vpc" "default" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "main" {
  vpc_id            = "${aws_vpc.default.id}"
  availability_zone = "${var.aws_availability_zone}"
  cidr_block        = "10.0.0.0/16"
}

# Create a gateway for our VPC
resource "aws_internet_gateway" "default" {
  vpc_id = "${aws_vpc.default.id}"
}

# We'll need to add a route to the internet from our VPC
resource "aws_route" "internet_access" {
  route_table_id         = "${aws_vpc.default.main_route_table_id}"
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = "${aws_internet_gateway.default.id}"
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
  name              = "minecraft"
  image_id          = "${data.aws_ami.ubuntu.id}"
  instance_type     = "i3.large"
  spot_price        = "${var.max_spot_price}"
  ebs_optimized     = false
  enable_monitoring = false

  # Has no key associated for accessing the instance
  # Has no block device mounted, is one necessary?

  iam_instance_profile = "${aws_iam_instance_profile.minecraft.name}"
  security_groups      = ["${aws_security_group.default.id}"]
  key_name             = "aws-public"
}

# Autoscaling Group
resource "aws_autoscaling_group" "minecraft" {
  vpc_zone_identifier = ["${aws_subnet.main.id}"]

  name                 = "minecraft"
  desired_capacity     = 0
  min_size             = 0
  max_size             = 1
  launch_configuration = "${aws_launch_configuration.minecraft.name}"

  tags = []
}
