"""Supabase Storage implementation of the artifact storage contract."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from pydantic import SecretStr

from . import filesystem
from .base import (
    ArtifactAccessDenied,
    ArtifactDownload,
    ArtifactKey,
    ArtifactNotFound,
    ArtifactStore,
    ArtifactStoreError,
    InvalidArtifactKey,
)


_BUCKET_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _secret_value(secret: SecretStr | str) -> str:
    if isinstance(secret, SecretStr):
        return secret.get_secret_value()
    return str(secret)


def _validate_bucket(bucket: str, label: str) -> str:
    if not isinstance(bucket, str) or not bucket or bucket in {".", ".."}:
        raise InvalidArtifactKey(f"invalid {label}")
    if "/" in bucket or "\\" in bucket:
        raise InvalidArtifactKey(f"{label} must be one path segment")
    if _BUCKET_SEGMENT.fullmatch(bucket) is None:
        raise InvalidArtifactKey(f"{label} contains unsafe characters")
    return bucket


class SupabaseArtifactStore(ArtifactStore):
    """Private Supabase Storage adapter using service-role server credentials."""

    def __init__(
        self,
        supabase_url: str,
        backend_secret: SecretStr | str,
        originals_bucket: str,
        results_bucket: str,
        *,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        write_timeout: float = 30.0,
        pool_timeout: float = 5.0,
        signed_url_expires_in_seconds: int = 300,
        upload_chunk_size: int = 1024 * 1024,
        materialize_chunk_size: int = 1024 * 1024,
        list_page_size: int = 100,
    ) -> None:
        self._origin = str(supabase_url).rstrip("/")
        if not self._origin.startswith(("https://", "http://")):
            raise ArtifactStoreError("invalid Supabase URL")
        self._storage_url = f"{self._origin}/storage/v1"
        self._secret = _secret_value(backend_secret)
        if not self._secret.strip():
            raise ArtifactStoreError("Supabase backend secret is required")
        self._originals_bucket = _validate_bucket(
            originals_bucket, "originals bucket"
        )
        self._results_bucket = _validate_bucket(results_bucket, "results bucket")
        if signed_url_expires_in_seconds <= 0:
            raise ArtifactStoreError("signed URL expiry must be positive")
        if min(upload_chunk_size, materialize_chunk_size, list_page_size) <= 0:
            raise ArtifactStoreError("Supabase storage limits must be positive")
        self._signed_url_expires_in_seconds = signed_url_expires_in_seconds
        self._upload_chunk_size = upload_chunk_size
        self._materialize_chunk_size = materialize_chunk_size
        self._list_page_size = list_page_size
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=write_timeout,
                pool=pool_timeout,
            ),
            transport=transport,
        )

    def put(
        self,
        user_id: str,
        job_id: str,
        kind: str,
        source: Path,
        filename: str | None = None,
    ) -> str:
        source_path = Path(source)
        artifact = ArtifactKey(
            user_id,
            job_id,
            kind,
            source_path.name if filename is None else filename,
        )
        filesystem.validate_regular_source(source_path)

        def body() -> Iterable[bytes]:
            with source_path.open("rb") as file:
                while chunk := file.read(self._upload_chunk_size):
                    yield chunk

        response = self._request(
            "POST",
            self._object_url(self._bucket_for(artifact), artifact.key),
            headers=self._headers({"x-upsert": "true"}),
            content=body(),
        )
        self._raise_for_status(response, not_found=ArtifactNotFound)
        return artifact.key

    def materialize(
        self,
        user_id: str,
        key: str,
        destination: Path,
        *,
        destination_root: Path,
    ) -> Path:
        artifact = ArtifactKey.parse(key).for_owner(user_id)
        destination_path, boundary = filesystem.safe_materialization_destination(
            destination, destination_root
        )
        with filesystem.process_lock_for(boundary):
            destination_path, boundary = filesystem.safe_materialization_destination(
                destination, destination_root
            )
            url = self._object_url(self._bucket_for(artifact), artifact.key)
            try:
                with self._client.stream("GET", url, headers=self._headers()) as response:
                    self._raise_for_status(response, not_found=ArtifactNotFound)
                    filesystem.atomic_write_chunks(
                        response.iter_bytes(self._materialize_chunk_size),
                        destination_path,
                        boundary=boundary,
                    )
            except httpx.HTTPError as exc:
                raise ArtifactStoreError("Supabase storage request failed") from exc
        return Path(destination)

    def download(self, user_id: str, key: str) -> ArtifactDownload:
        artifact = ArtifactKey.parse(key).for_owner(user_id)
        bucket = self._bucket_for(artifact)
        response = self._request(
            "POST",
            self._sign_url(bucket, artifact.key),
            headers=self._headers(),
            json={"expiresIn": self._signed_url_expires_in_seconds},
        )
        self._raise_for_status(response, not_found=ArtifactNotFound)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ArtifactStoreError("Supabase signed URL response is invalid") from exc
        if not isinstance(payload, dict):
            raise ArtifactStoreError("Supabase signed URL response is invalid")
        signed_url = payload.get("signedURL")
        if not isinstance(signed_url, str) or not signed_url:
            raise ArtifactStoreError("Supabase signed URL response is invalid")
        return ArtifactDownload(
            signed_url=self._validated_signed_url(bucket, artifact.key, signed_url),
            expires_in_seconds=self._signed_url_expires_in_seconds,
        )

    def delete(self, user_id: str, key: str) -> None:
        artifact = ArtifactKey.parse(key).for_owner(user_id)
        self._delete_prefixes(self._bucket_for(artifact), [artifact.key])

    def delete_job(self, user_id: str, job_id: str) -> None:
        marker = ArtifactKey(user_id, job_id, "original", "validation")
        prefix = f"users/{marker.user_id}/jobs/{marker.job_id}/"
        for bucket in dict.fromkeys((self._originals_bucket, self._results_bucket)):
            keys = self._list_owned_job_keys(bucket, marker.user_id, marker.job_id, prefix)
            if keys:
                self._delete_prefixes(bucket, keys)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "authorization": f"Bearer {self._secret}",
            "apikey": self._secret,
        }
        if extra:
            headers.update(extra)
        return headers

    def _bucket_for(self, artifact: ArtifactKey) -> str:
        if artifact.kind == "original":
            return self._originals_bucket
        return self._results_bucket

    def _object_url(self, bucket: str, key: str) -> str:
        return f"{self._storage_url}/object/{self._quote_bucket(bucket)}/{self._quote_key(key)}"

    def _sign_url(self, bucket: str, key: str) -> str:
        return (
            f"{self._storage_url}/object/sign/"
            f"{self._quote_bucket(bucket)}/{self._quote_key(key)}"
        )

    def _list_url(self, bucket: str) -> str:
        return f"{self._storage_url}/object/list/{self._quote_bucket(bucket)}"

    def _delete_url(self, bucket: str) -> str:
        return f"{self._storage_url}/object/{self._quote_bucket(bucket)}"

    def _quote_bucket(self, bucket: str) -> str:
        return quote(bucket, safe="")

    def _quote_key(self, key: str) -> str:
        return quote(key, safe="/")

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise ArtifactStoreError("Supabase storage request failed") from exc

    def _raise_for_status(
        self,
        response: httpx.Response,
        *,
        not_found: type[ArtifactStoreError] = ArtifactNotFound,
        not_found_ok: bool = False,
    ) -> None:
        if 200 <= response.status_code < 300:
            return
        if response.status_code == 404 and not_found_ok:
            return
        if response.status_code in {401, 403}:
            raise ArtifactAccessDenied("Supabase storage access denied")
        if response.status_code == 404:
            raise not_found("Supabase artifact does not exist")
        if response.status_code in {409, 429} or response.status_code >= 500:
            raise ArtifactStoreError("Supabase storage request failed")
        raise ArtifactStoreError("Supabase storage request was rejected")

    def _validated_signed_url(self, bucket: str, key: str, signed_url: str) -> str:
        expected_path = f"/storage/v1/object/sign/{self._quote_bucket(bucket)}/{self._quote_key(key)}"
        parsed = urlsplit(signed_url)
        if parsed.scheme or parsed.netloc:
            origin = f"{parsed.scheme}://{parsed.netloc}"
            absolute = signed_url
        elif signed_url.startswith("/"):
            origin = self._origin
            absolute = f"{self._origin}{signed_url}"
            parsed = urlsplit(absolute)
        else:
            raise ArtifactStoreError("Supabase signed URL response is invalid")
        if origin != self._origin or parsed.path != expected_path:
            raise ArtifactStoreError("Supabase signed URL response is invalid")
        return absolute

    def _delete_prefixes(self, bucket: str, keys: list[str]) -> None:
        response = self._request(
            "DELETE",
            self._delete_url(bucket),
            headers=self._headers(),
            json={"prefixes": keys},
        )
        self._raise_for_status(response, not_found_ok=True)

    def _list_owned_job_keys(
        self, bucket: str, user_id: str, job_id: str, prefix: str
    ) -> list[str]:
        keys: list[str] = []
        offset = 0
        while True:
            response = self._request(
                "POST",
                self._list_url(bucket),
                headers=self._headers(),
                json={
                    "prefix": prefix,
                    "limit": self._list_page_size,
                    "offset": offset,
                },
            )
            self._raise_for_status(response, not_found_ok=True)
            try:
                payload = response.json()
            except ValueError as exc:
                raise ArtifactStoreError("Supabase list response is invalid") from exc
            if payload in (None, {}):
                break
            if not isinstance(payload, list):
                raise ArtifactStoreError("Supabase list response is invalid")
            if not payload:
                break
            for entry in payload:
                object_key = self._object_key_from_list_entry(prefix, entry)
                if not object_key.startswith(prefix):
                    raise ArtifactStoreError("Supabase list returned an unsafe object")
                artifact = ArtifactKey.parse(object_key).for_owner(user_id)
                if artifact.job_id != job_id or self._bucket_for(artifact) != bucket:
                    raise ArtifactStoreError("Supabase list returned an unsafe object")
                keys.append(artifact.key)
            offset += len(payload)
        return keys

    def _object_key_from_list_entry(self, prefix: str, entry: Any) -> str:
        if not isinstance(entry, dict):
            raise ArtifactStoreError("Supabase list response is invalid")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ArtifactStoreError("Supabase list response is invalid")
        if name.startswith(prefix):
            return name
        return f"{prefix}{name}"
