import io
from minio import Minio
from minio.error import S3Error
from app.core.config import (
    MINIO_HOST,
    MINIO_ACCESS_KEY,
    MINIO_SECRET_KEY,
    MINIO_BUCKET
)

def get_client():
    return Minio(
        MINIO_HOST,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False
    )

def ensure_bucket():
    client = get_client()
    if not client.bucket_exists(MINIO_BUCKET):
        client.make_bucket(MINIO_BUCKET)
        print(f" Bucket '{MINIO_BUCKET}' created")
    else:
        print(f"ℹ  Bucket '{MINIO_BUCKET}' already exists")

def upload_file(file_bytes: bytes, filename: str, content_type: str) -> str:
    try:
        client = get_client()
        ensure_bucket()
        client.put_object(
            MINIO_BUCKET,
            filename,
            data=io.BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type
        )
        minio_path = f"{MINIO_BUCKET}/{filename}"
        print(f"Uploaded: {minio_path}")
        return minio_path
    except S3Error as e:
        print(f" Upload failed: {e}")
        raise

def download_file(filename: str) -> bytes:
    try:
        client = get_client()
        response = client.get_object(MINIO_BUCKET, filename)
        return response.read()
    except S3Error as e:
        print(f" Download failed: {e}")
        raise

def delete_file(filename: str):
    try:
        client = get_client()
        client.remove_object(MINIO_BUCKET, filename)
        print(f"  Deleted: {filename}")
    except S3Error as e:
        print(f" Delete failed: {e}")
        raise

def list_files() -> list:
    try:
        client = get_client()
        objects = client.list_objects(MINIO_BUCKET)
        return [
            {
                "filename": obj.object_name,
                "size":     obj.size,
                "uploaded": obj.last_modified
            }
            for obj in objects
        ]
    except S3Error as e:
        print(f" List failed: {e}")
        raise