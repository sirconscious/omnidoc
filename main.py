from dotenv import load_dotenv
import os

load_dotenv()  

MINIO_HOST = os.getenv("MINIO_HOST")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")

print(MINIO_HOST, MINIO_ACCESS_KEY, MINIO_SECRET_KEY)