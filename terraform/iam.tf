# Unique IAM role for the server
resource "aws_iam_role" "minecraft_role" {
  name               = "minecraft2"
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

# Assigns policies to the server role, in this case we allow all operations on
# our S3 bucket
resource "aws_iam_role_policy" "minecraft_policy" {
  name   = "minecraft_policy"
  role   = "${aws_iam_role.minecraft_role.id}"
  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:*",
      "Resource": "*"
    }
  ]
}
EOF
}



