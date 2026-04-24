remote_state {
  backend = "s3"
  config = {
    bucket         = "klar-assets-klar-terraform-state"
    key            = "${path_relative_to_include()}/terraform.tfstate"
    encrypt        = true
    region         = "us-east-2" 
    dynamodb_table = "klar-assets-klar-terraform-state"
  }
}

iam_role = "arn:aws:iam::739282534308:role/Admin"
