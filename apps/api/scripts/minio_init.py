from minio import Minio

from canonguard.core.config import get_settings


def main() -> None:
    settings = get_settings()
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    buckets = [settings.minio_bucket_sources, settings.minio_bucket_artifacts]
    for bucket in buckets:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            print(f"created bucket {bucket}")
        else:
            print(f"bucket {bucket} already exists")


if __name__ == "__main__":
    main()
