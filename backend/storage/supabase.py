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
    ArtifactConflictError,
    ArtifactDownload,
    ArtifactKey,
    ArtifactNotFound,
    ArtifactRetryableError,
    ArtifactStore,
    ArtifactStoreError,
    InvalidArtifactKey,
)


_BUCKET_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PROJECT_REF = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")


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


def _validate_endpoint(supabase_url: str, project_ref: str) -> str:
    if not isinstance(project_ref, str) or _PROJECT_REF.fullmatch(project_ref) is None:
        raise ArtifactStoreError("invalid Supabase project reference")
    try:
        parsed = urlsplit(str(supabase_url))
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ArtifactStoreError("invalid Supabase URL") from exc
    expected_hostname = f"{project_ref}.supabase.co"
    if (
        parsed.scheme != "https"
        or parsed.hostname != expected_hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or parsed.netloc != expected_hostname
    ):
        raise ArtifactStoreError("invalid Supabase URL")
    return f"https://{expected_hostname}"


class SupabaseArtifactStore(ArtifactStore):
    """Private Supabase Storage adapter using service-role server credentials."""

    def __init__(
        self,
        supabase_url: str,
        backend_secret: SecretStr | str,
        originals_bucket: str,
        results_bucket: str,
        *,
        project_ref: str,
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
        self._origin = _validate_endpoint(supabase_url, project_ref)
        self._storage_url = f"{self._origin}/storage/v1"
        self._secret = _secret_value(backend_secret)
        if not self._secret.strip():
            raise ArtifactStoreError("Supabase backend secret is required")
        self._originals_bucket = _validate_bucket(
            originals_bucket, "originals bucket"
        )
        self._results_bucket = _validate_bucket(results_bucket, "results bucket")
        if self._originals_bucket == self._results_bucket:
            raise InvalidArtifactKey("Supabase artifact buckets must be distinct")
        if signed_url_expires_in_seconds <= 0:
            raise ArtifactStoreError("signed URL expiry must be positive")
        if min(upload_chunk_size, materialize_chunk_size, list_page_size) <= 0:
            raise ArtifactStoreError("Supabase storage limits must be positive")
        self._signed_url_expires_in_seconds = signed_url_expires_in_seconds
        self._upload_chunk_size = upload_chunk_size
        self._materialize_chunk_size = materialize_chunk_size
        self._list_page_size = min(list_page_size, 1000)
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
                raise ArtifactRetryableError(
                    "Supabase storage request failed"
                ) from exc
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
        job_prefix = f"users/{marker.user_id}/jobs/{marker.job_id}"
        kind_locations = (
            (self._originals_bucket, "original"),
            (self._results_bucket, "remediated"),
            (self._results_bucket, "report"),
        )
        for bucket, kind in kind_locations:
            prefix = f"{job_prefix}/{kind}"
            previous_page: frozenset[str] | None = None
            while True:
                keys = self._list_owned_kind_keys(
                    bucket, marker.user_id, marker.job_id, kind, prefix
                )
                if not keys:
                    break
                page = frozenset(keys)
                if page == previous_page:
                    raise ArtifactStoreError("Supabase delete made no progress")
                self._delete_prefixes(bucket, keys)
                previous_page = page

    def close(self) -> None:
        if self._owns_client and not self._client.is_closed:
            self._client.close()

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
            raise ArtifactRetryableError("Supabase storage request failed") from exc

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
        if response.status_code == 409:
            raise ArtifactConflictError("Supabase storage request conflicted")
        if response.status_code == 429 or response.status_code >= 500:
            raise ArtifactRetryableError("Supabase storage request failed")
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

    def _list_owned_kind_keys(
        self,
        bucket: str,
        user_id: str,
        job_id: str,
        kind: str,
        prefix: str,
    ) -> list[str]:
        response = self._request(
            "POST",
            self._list_url(bucket),
            headers=self._headers(),
            json={"prefix": prefix, "limit": self._list_page_size, "offset": 0},
        )
        self._raise_for_status(response, not_found_ok=True)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ArtifactStoreError("Supabase list response is invalid") from exc
        if payload in (None, {}) or payload == []:
            return []
        if not isinstance(payload, list) or len(payload) > self._list_page_size:
            raise ArtifactStoreError("Supabase list response is invalid")
        keys: list[str] = []
        for entry in payload:
            object_key = self._object_key_from_list_entry(prefix, entry)
            try:
                artifact = ArtifactKey.parse(object_key).for_owner(user_id)
            except (InvalidArtifactKey, ArtifactAccessDenied) as exc:
                raise ArtifactStoreError("Supabase list returned an unsafe object") from exc
            if (
                artifact.job_id != job_id
                or artifact.kind != kind
                or self._bucket_for(artifact) != bucket
                or artifact.key != object_key
            ):
                raise ArtifactStoreError("Supabase list returned an unsafe object")
            keys.append(artifact.key)
        if len(set(keys)) != len(keys):
            raise ArtifactStoreError("Supabase list response is invalid")
        return keys

    def _object_key_from_list_entry(self, prefix: str, entry: Any) -> str:
        if not isinstance(entry, dict):
            raise ArtifactStoreError("Supabase list response is invalid")
        object_id = entry.get("id")
        if object_id is None:
            raise ArtifactStoreError("Supabase list returned an unexpected folder")
        if not isinstance(object_id, str) or not object_id:
            raise ArtifactStoreError("Supabase list response is invalid")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ArtifactStoreError("Supabase list response is invalid")
        if name.startswith("users/"):
            if not name.startswith(f"{prefix}/"):
                raise ArtifactStoreError("Supabase list returned an unsafe object")
            return name
        if name in {".", ".."} or "/" in name or "\\" in name:
            raise ArtifactStoreError("Supabase list returned an unsafe object")
        return f"{prefix}/{name}"
