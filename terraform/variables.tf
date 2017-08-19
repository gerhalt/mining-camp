variable "minecraft" {
  type = "map"

  default = {
    port        = 25565
    bucket_name = "josh-minecraft"
  }
}

variable "max_spot_price" {
  description = "Maximum amount to pay for per spot instance per hour."
  default     = "0.06"
}

variable "aws_region" {
  description = "AWS region to launch servers in."
  default     = "us-east-1"
}

variable "aws_availability_zones" {
  description = "AWS availability zones to launch servers in."
  default     = ["us-east-1d"]
}
