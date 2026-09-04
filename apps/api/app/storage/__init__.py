from app.storage.base import ObjectStorage
from app.storage.s3 import S3ObjectStorage, get_object_storage

__all__ = ["ObjectStorage", "S3ObjectStorage", "get_object_storage"]
