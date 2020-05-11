# Unique IAM role for the server
resource "aws_iam_role" "minecraft" {
  name               = "minecraft"
  description        = "S3 Access"
  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      },
      "Effect": "Allow",
      "Sid": ""
    }
  ]
}
EOF
}

# When not done in the AWS control panel, an instance profile isn't created
# automatically when a role is created.
resource "aws_iam_instance_profile" "minecraft" {
  name = "minecraft"
  role = aws_iam_role.minecraft.name
}

# Assigns policies to the server role, in this case we allow all operations on
# our S3 bucket
resource "aws_iam_role_policy" "minecraft" {
  name   = "minecraft"
  role   = aws_iam_role.minecraft.id
  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:*",
      "Resource": [
        "${aws_s3_bucket.minecraft.arn}",
        "${aws_s3_bucket.minecraft.arn}/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "route53:*",
      "Resource": "arn:aws:route53:::hostedzone/${aws_route53_zone.minecraft.zone_id}"
    },
    {
      "Effect": "Allow",
      "Action": [
        "route53:ListHostedZonesByName"
      ],
      "Resource": "*"
    }
  ]
}
EOF
}



