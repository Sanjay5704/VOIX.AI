"""Object storage behind one small interface.

`LocalStorage` keeps files under a directory and streams them through the
API's authorized download routes. `S3Storage` targets any S3-compatible
store (Cloudflare R2 in the deploy guide) and answers downloads with a
short-lived presigned redirect, so audio never transits the API process.

Keys are always generated server-side from UUIDs (e.g. `jobs/<uuid>/audio.mp3`),
never from user input.
"""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO, Protocol

from fastapi.responses import FileResponse, RedirectResponse, Response

from voix_api.config import Settings, get_settings


class Storage(Protocol):
    def put(self, key: str, fileobj: BinaryIO, content_type: str) -> int: ...

    def delete(self, key: str) -> None: ...

    def exists(self, key: str) -> bool: ...

    def download_response(self, key: str, filename: str, media_type: str) -> Response: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"Storage key escapes root: {key!r}")
        return path

    def put(self, key: str, fileobj: BinaryIO, content_type: str) -> int:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as out:
            shutil.copyfileobj(fileobj, out, length=1024 * 1024)
        return path.stat().st_size

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def download_response(self, key: str, filename: str, media_type: str) -> Response:
        return FileResponse(self._path(key), media_type=media_type, filename=filename)


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = settings.s3_bucket
        self.ttl = settings.s3_presign_ttl_seconds
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def put(self, key: str, fileobj: BinaryIO, content_type: str) -> int:
        fileobj.seek(0, 2)
        size = fileobj.tell()
        fileobj.seek(0)
        self.client.upload_fileobj(fileobj, self.bucket, key, ExtraArgs={"ContentType": content_type})
        return size

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def download_response(self, key: str, filename: str, media_type: str) -> Response:
        url = self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentType": media_type,
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
            },
            ExpiresIn=self.ttl,
        )
        return RedirectResponse(url, status_code=302)


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage(settings.local_storage_dir)


@lru_cache
def _default_storage() -> Storage:
    return build_storage(get_settings())


def get_storage() -> Storage:
    """FastAPI dependency (overridden in tests)."""
    return _default_storage()
