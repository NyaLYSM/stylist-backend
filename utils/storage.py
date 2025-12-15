# storage.py
import os
import uuid
from typing import Tuple, Optional

# Опции: "s3" или "local"
STORAGE_TYPE = os.getenv("STORAGE_TYPE", "local")  # set to "s3" to enable S3
LOCAL_DIR = os.getenv("LOCAL_IMAGE_DIR", "static/images")  # relative to project root

# Для S3 (если включено)
S3_BUCKET = os.getenv("S3_BUCKET")
S3_PREFIX = os.getenv("S3_PREFIX", "images/")

S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "https://storage.yandexcloud.net")

if STORAGE_TYPE == "local":
    os.makedirs(LOCAL_DIR, exist_ok=True)


def save_image_local(filename: str, data: bytes) -> str:
    # Генерация уникального имени
    ext = os.path.splitext(filename)[1] or ".jpg"
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(LOCAL_DIR, name)
    with open(path, "wb") as f:
        f.write(data)
    # Возвращаем публичный относительный путь — предполагаем, что webserver отдаёт /static/
    return f"/static/images/{name}"


# Optional: S3 uploader (requires boto3)
def save_image_s3(filename: str, data: bytes) -> str:
    import boto3
    if not S3_BUCKET:
        raise RuntimeError("S3_BUCKET не настроен")
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_REGION")
    )
    ext = os.path.splitext(filename)[1] or ".jpg"
    key = f"{S3_PREFIX}{uuid.uuid4().hex}{ext}"
    s3.put_object(Bucket=S3_BUCKET, Key=key, Body=data, ACL="public-read", ContentType="image/jpeg")
    # Конструируем публичный URL (пример для AWS)
    return f"https://{S3_BUCKET}.storage.yandexcloud.net/{key}"


def save_image(filename: str, data: bytes) -> str:
    if STORAGE_TYPE == "s3":
        return save_image_s3(filename, data)
    return save_image_local(filename, data)


def delete_image(public_url: str) -> bool:
    """Удаление изображения — реализация зависит от STORAGE_TYPE.
       Для локального - удаляем файл, для S3 - удаляем ключ.
    """
    try:
        if STORAGE_TYPE == "s3":
            # выдернем ключ из URL (простейший подход)
            from urllib.parse import urlparse
            u = urlparse(public_url)
            key = u.path.lstrip('/')
            import boto3
            s3 = boto3.client(
                "s3",
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                region_name=os.getenv("AWS_REGION")
            )
            s3.delete_object(Bucket=S3_BUCKET, Key=key)
            return True
        else:
            # локальный — public_url ожидается вида /static/images/<name>
            path = public_url.split("/static/")[-1] if "/static/" in public_url else public_url
            fs_path = os.path.join(os.getcwd(), "static", path)
            if os.path.exists(fs_path):
                os.remove(fs_path)
                return True
            return False
    except Exception as e:
        print("delete_image error:", e)
        return False
