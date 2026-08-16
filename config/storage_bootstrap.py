import json
import os
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

TRUE_VALUES = {"1", "true", "yes", "on"}


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in TRUE_VALUES


def create_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        region_name=os.getenv(
            "S3_REGION_NAME",
            "us-east-1",
        ),
        config=Config(
            signature_version="s3v4",
            s3={
                "addressing_style": os.getenv(
                    "S3_ADDRESSING_STYLE",
                    "path",
                )
            },
        ),
    )


def public_read_policy(bucket_name: str) -> str:
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "LeagueOSPublicMediaRead",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket_name}/*",
            }
        ],
    }

    return json.dumps(
        policy,
        separators=(",", ":"),
        sort_keys=True,
    )


def configure_object_storage():
    public_bucket = os.environ["S3_PUBLIC_BUCKET_NAME"]
    private_bucket = os.environ["S3_PRIVATE_BUCKET_NAME"]

    attempts = int(
        os.getenv(
            "S3_BOOTSTRAP_MAX_ATTEMPTS",
            "30",
        )
    )
    retry_seconds = float(
        os.getenv(
            "S3_BOOTSTRAP_RETRY_SECONDS",
            "2",
        )
    )

    client = create_client()

    for attempt in range(1, attempts + 1):
        try:
            existing = {
                item["Name"]
                for item in client.list_buckets().get(
                    "Buckets",
                    [],
                )
            }

            for bucket in (
                public_bucket,
                private_bucket,
            ):
                if bucket not in existing:
                    if not env_flag("S3_MANAGE_BUCKET_POLICIES"):
                        raise RuntimeError(f"Required S3 bucket does not exist: {bucket}")

                    client.create_bucket(Bucket=bucket)

            client.head_bucket(Bucket=public_bucket)
            client.head_bucket(Bucket=private_bucket)

            if env_flag("S3_MANAGE_BUCKET_POLICIES"):
                client.put_bucket_policy(
                    Bucket=public_bucket,
                    Policy=public_read_policy(public_bucket),
                )

            print(f"Public bucket OK: {public_bucket}")
            print(f"Private bucket OK: {private_bucket}")
            return

        except (
            BotoCoreError,
            ClientError,
            RuntimeError,
        ) as exc:
            if attempt == attempts:
                raise RuntimeError("Object-storage bootstrap failed.") from exc

            print("Object storage not ready; " f"retrying ({attempt}/{attempts}).")
            time.sleep(retry_seconds)


if __name__ == "__main__":
    configure_object_storage()
