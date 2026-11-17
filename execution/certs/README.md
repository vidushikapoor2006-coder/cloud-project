# AWS IoT credentials

This folder is where the AWS IoT device credentials go when running the optional AWS integration. They are not included in the repository.

Place your own files here, or point the environment variables in `execution/aws_iot_client.py` to them:

    AmazonRootCA1.pem
    <id>-certificate.pem.crt
    <id>-private.pem.key

These files are excluded by `.gitignore` and must never be committed.
