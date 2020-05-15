variable "minecraft" {
  type = map

  default = {
    port        = 25565
    bucket_name = "nerdhouse-minecraft"
  }
}

variable "max_spot_price" {
  description = "Maximum amount to pay for per spot instance per hour."
  default     = "0.7"
}

variable "aws_region" {
  description = "AWS region to launch servers in."
  default     = "us-east-1"
}

variable "aws_availability_zone" {
  description = "AWS availability zone to launch servers in."
  default     = "us-east-1e"
}

variable "aws_instance_type" {
  description = "Spot instance type to launch."
  default     = "m3.xlarge"
}