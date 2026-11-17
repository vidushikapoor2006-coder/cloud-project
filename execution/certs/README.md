# AWS IoT credentials (not distributed)

The original archive contained the AWS IoT device certificate and **private
key**. They were removed from the revised package. Place your own files here
(or point the environment variables in `execution/aws_iot_client.py` to them):

    AmazonRootCA1.pem
    <id>-certificate.pem.crt
    <id>-private.pem.key

Never commit these files; `.gitignore` excludes this directory's key files.
