from __future__ import annotations

import os
import stat
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from backend.storage import (
    ArtifactAccessDenied,
    ArtifactConflictError,
    ArtifactKey,
    ArtifactNotFound,
    ArtifactRetryableError,
    ArtifactStoreError,
    InvalidArtifactKey,
    SupabaseArtifactStore,
)


SECRET = "sb_secret_never_leak"
BASE_URL = "https://trial-project.supabase.co"


def _source(tmp_path: Path, content: bytes = b"artifact") -> Path:
    source = tmp_path / "source.pdf"
    source.write_bytes(content)
    return source


class Recorder:
    def __init__(self, responses: list[httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = responses or [httpx.Response(200, json={"ok": True})]

    def handler(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if self._responses:
            return self._responses.pop(0)
        return httpx.Response(200, json={"ok": True})


def _store(recorder: Recorder) -> SupabaseArtifactStore:
    return SupabaseArtifactStore(
        BASE_URL,
        SecretStr(SECRET),
        "trial-originals",
        "trial-results",
        project_ref="trial-project",
        transport=httpx.MockTransport(recorder.handler),
    )


def _json_body(request: httpx.Request) -> dict[str, Any]:
    return __import__("json").loads(request.content.decode("utf-8"))


@pytest.mark.parametrize(
    "bucket",
    ["", ".", "..", "nested/bucket", "nested\\bucket", "bucket name", "bad\x00name"],
)
def test_constructor_rejects_unsafe_bucket_names(bucket: str) -> None:
    with pytest.raises(InvalidArtifactKey):
        SupabaseArtifactStore(
            BASE_URL, SECRET, bucket, "trial-results", project_ref="trial-project"
        )
    with pytest.raises(InvalidArtifactKey):
        SupabaseArtifactStore(
            BASE_URL, SECRET, "trial-originals", bucket, project_ref="trial-project"
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://trial-project.supabase.co",
        "https://",
        "https://user@trial-project.supabase.co",
        "https://trial-project.supabase.co?secret=value",
        "https://trial-project.supabase.co#fragment",
        "https://trial-project.supabase.co/storage/v1",
        "https://trial-project.supabase.co:8443",
        "https://evil.example",
        "https://other-project.supabase.co",
    ],
)
def test_constructor_rejects_hostile_or_mismatched_endpoint(url: str) -> None:
    with pytest.raises(ArtifactStoreError, match="Supabase URL"):
        SupabaseArtifactStore(
            url,
            SECRET,
            "trial-originals",
            "trial-results",
            project_ref="trial-project",
        )


def test_constructor_requires_distinct_buckets() -> None:
    with pytest.raises(InvalidArtifactKey, match="distinct"):
        SupabaseArtifactStore(
            BASE_URL,
            SECRET,
            "trial-artifacts",
            "trial-artifacts",
            project_ref="trial-project",
        )


def test_put_uploads_original_to_originals_bucket_with_canonical_key_and_secret_headers(
    tmp_path: Path,
) -> None:
    recorder = Recorder([httpx.Response(201, json={"Key": "ignored-provider-key"})])
    store = _store(recorder)

    key = store.put("user-1", "job-1", "original", _source(tmp_path), "RÃ©sumÃ©.pdf")

    assert key == "users/user-1/jobs/job-1/original/RÃ©sumÃ©.pdf"
    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request.method == "POST"
    assert str(request.url) == (
        "https://trial-project.supabase.co/storage/v1/object/"
        "trial-originals/users/user-1/jobs/job-1/original/R%C3%83%C2%A9sum%C3%83%C2%A9.pdf"
    )
    assert request.headers["authorization"] == f"Bearer {SECRET}"
    assert request.headers["apikey"] == SECRET
    assert request.headers["x-upsert"] == "true"
    assert request.content == b"artifact"


@pytest.mark.parametrize("kind", ["remediated", "report"])
def test_put_maps_remediated_and_report_to_results_bucket(
    tmp_path: Path, kind: str
) -> None:
    recorder = Recorder([httpx.Response(200, json={})])
    store = _store(recorder)

    key = store.put("user", "job", kind, _source(tmp_path), "result.pdf")

    assert key == f"users/user/jobs/job/{kind}/result.pdf"
    assert "/storage/v1/object/trial-results/" in str(recorder.requests[0].url)


@pytest.mark.parametrize(
    ("status", "exception"),
    [
        (401, ArtifactAccessDenied),
        (403, ArtifactAccessDenied),
        (404, ArtifactNotFound),
        (409, ArtifactConflictError),
        (429, ArtifactRetryableError),
        (500, ArtifactRetryableError),
        (418, ArtifactStoreError),
    ],
)
def test_put_maps_storage_errors_without_leaking_secret(
    tmp_path: Path, status: int, exception: type[Exception]
) -> None:
    recorder = Recorder([httpx.Response(status, text=f"server body {SECRET}")])
    store = _store(recorder)

    with pytest.raises(exception) as captured:
        store.put("user", "job", "original", _source(tmp_path))

    assert SECRET not in str(captured.value)
    assert "server body" not in str(captured.value)


def test_put_rejects_non_regular_reparse_source_without_http(
    tmp_path: Path,
) -> None:
    recorder = Recorder()
    store = _store(recorder)

    with pytest.raises(ArtifactStoreError):
        store.put("user", "job", "original", tmp_path)

    assert recorder.requests == []


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("offline"), httpx.ReadTimeout("slow")],
)
def test_network_and_timeout_failures_are_retryable_without_leaking_details(
    tmp_path: Path, failure: httpx.HTTPError
) -> None:
    def fail(_request: httpx.Request) -> httpx.Response:
        raise failure

    store = SupabaseArtifactStore(
        BASE_URL,
        SECRET,
        "trial-originals",
        "trial-results",
        project_ref="trial-project",
        transport=httpx.MockTransport(fail),
    )

    with pytest.raises(ArtifactRetryableError) as captured:
        store.put("user", "job", "original", _source(tmp_path))

    assert "offline" not in str(captured.value)
    assert "slow" not in str(captured.value)


def test_download_rejects_cross_user_before_http() -> None:
    recorder = Recorder()
    store = _store(recorder)
    key = ArtifactKey("other-user", "job", "report", "report.json").key

    with pytest.raises(ArtifactAccessDenied):
        store.download("user", key)

    assert recorder.requests == []


def test_download_returns_signed_url_expiring_in_300_seconds() -> None:
    recorder = Recorder(
        [
            httpx.Response(
                200,
                json={
                    "signedURL": (
                        "/storage/v1/object/sign/trial-results/"
                        "users/user/jobs/job/report/report.json?token=signed"
                    )
                },
            )
        ]
    )
    store = _store(recorder)
    key = ArtifactKey("user", "job", "report", "report.json").key

    download = store.download("user", key)

    assert download.signed_url == (
        "https://trial-project.supabase.co/storage/v1/object/sign/trial-results/"
        "users/user/jobs/job/report/report.json?token=signed"
    )
    assert download.local_path is None
    assert download.expires_in_seconds == 300
    request = recorder.requests[0]
    assert request.method == "POST"
    assert str(request.url) == (
        "https://trial-project.supabase.co/storage/v1/object/sign/"
        "trial-results/users/user/jobs/job/report/report.json"
    )
    assert _json_body(request) == {"expiresIn": 300}
    assert request.headers["authorization"] == f"Bearer {SECRET}"
    assert request.headers["apikey"] == SECRET


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"signedURL": ""},
        {"signedURL": "https://evil.example/object/report.json"},
        {"signedURL": "/storage/v1/object/public/trial-results/report.json"},
    ],
)
def test_download_rejects_malformed_signed_url_without_leaking_secret(
    payload: dict[str, str],
) -> None:
    recorder = Recorder([httpx.Response(200, json=payload)])
    store = _store(recorder)

    with pytest.raises(ArtifactStoreError) as captured:
        store.download("user", ArtifactKey("user", "job", "report", "report.json").key)

    assert SECRET not in str(captured.value)


def test_materialize_streams_private_object_to_safe_destination(tmp_path: Path) -> None:
    recorder = Recorder([httpx.Response(200, content=b"private artifact")])
    store = _store(recorder)
    destination_root = tmp_path / "exports"
    destination = destination_root / "nested" / "copy.pdf"
    key = ArtifactKey("user", "job", "remediated", "copy.pdf").key

    result = store.materialize(
        "user", key, destination, destination_root=destination_root
    )

    assert result == destination
    assert destination.read_bytes() == b"private artifact"
    if os.name != "nt":
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    request = recorder.requests[0]
    assert request.method == "GET"
    assert str(request.url) == (
        "https://trial-project.supabase.co/storage/v1/object/"
        "trial-results/users/user/jobs/job/remediated/copy.pdf"
    )
    assert request.headers["authorization"] == f"Bearer {SECRET}"
    assert request.headers["apikey"] == SECRET


def test_materialize_rejects_unsafe_destination_before_http(tmp_path: Path) -> None:
    recorder = Recorder([httpx.Response(200, content=b"should not be read")])
    store = _store(recorder)
    destination_root = tmp_path / "exports"

    with pytest.raises(ArtifactAccessDenied):
        store.materialize(
            "user",
            ArtifactKey("user", "job", "original", "source.pdf").key,
            destination_root / ".." / "escaped.pdf",
            destination_root=destination_root,
        )

    assert recorder.requests == []
    assert not (tmp_path / "escaped.pdf").exists()


def test_materialize_cleans_temp_file_after_http_error(tmp_path: Path) -> None:
    recorder = Recorder([httpx.Response(500, text=f"fail {SECRET}")])
    store = _store(recorder)
    destination_root = tmp_path / "exports"
    destination = destination_root / "copy.pdf"

    with pytest.raises(ArtifactStoreError) as captured:
        store.materialize(
            "user",
            ArtifactKey("user", "job", "original", "source.pdf").key,
            destination,
            destination_root=destination_root,
        )

    assert SECRET not in str(captured.value)
    assert not destination.exists()
    assert not list(destination_root.glob("*.tmp"))


def test_materialize_maps_stream_transport_failure_to_retryable(tmp_path: Path) -> None:
    def fail(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("do not expose")

    store = SupabaseArtifactStore(
        BASE_URL,
        SECRET,
        "trial-originals",
        "trial-results",
        project_ref="trial-project",
        transport=httpx.MockTransport(fail),
    )

    with pytest.raises(ArtifactRetryableError) as captured:
        store.materialize(
            "user",
            ArtifactKey("user", "job", "original", "source.pdf").key,
            tmp_path / "exports" / "copy.pdf",
            destination_root=tmp_path / "exports",
        )

    assert "do not expose" not in str(captured.value)


def test_materialize_uses_shared_destination_root_process_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = Recorder(
        [
            httpx.Response(200, content=b"first"),
            httpx.Response(200, content=b"second"),
        ]
    )
    first = _store(recorder)
    second = _store(recorder)
    destination_root = tmp_path / "exports"
    destination = destination_root / "copy.pdf"
    key = ArtifactKey("user", "job", "original", "source.pdf").key
    entered = threading.Event()
    release = threading.Event()
    calls: list[Path] = []
    original_atomic_write = __import__(
        "backend.storage.filesystem", fromlist=["atomic_write_chunks"]
    ).atomic_write_chunks

    def controlled_atomic_write(chunks, target: Path, *, boundary: Path) -> None:
        calls.append(target)
        if len(calls) == 1:
            entered.set()
            assert release.wait(timeout=5)
        original_atomic_write(chunks, target, boundary=boundary)

    monkeypatch.setattr(
        "backend.storage.supabase.filesystem.atomic_write_chunks",
        controlled_atomic_write,
    )
    errors: list[BaseException] = []

    def materialize(store: SupabaseArtifactStore) -> None:
        try:
            store.materialize("user", key, destination, destination_root=destination_root)
        except BaseException as exc:
            errors.append(exc)

    thread_one = threading.Thread(target=materialize, args=(first,))
    thread_two = threading.Thread(target=materialize, args=(second,))
    thread_one.start()
    assert entered.wait(timeout=5)
    thread_two.start()
    time.sleep(0.1)
    assert calls == [destination.absolute()]
    release.set()
    thread_one.join(timeout=5)
    thread_two.join(timeout=5)

    assert not errors
    assert len(calls) == 2


def test_delete_uses_storage_batch_delete_and_404_is_idempotent() -> None:
    recorder = Recorder([httpx.Response(404, json={})])
    store = _store(recorder)

    store.delete("user", ArtifactKey("user", "job", "report", "report.json").key)

    request = recorder.requests[0]
    assert request.method == "DELETE"
    assert str(request.url) == (
        "https://trial-project.supabase.co/storage/v1/object/trial-results"
    )
    assert _json_body(request) == {
        "prefixes": ["users/user/jobs/job/report/report.json"]
    }


def test_delete_job_paginates_both_buckets_and_batch_deletes_exact_owned_keys() -> None:
    responses = [
        httpx.Response(
            200,
            json=[
                {"name": "users/user/jobs/job/original/a.pdf"},
                {"name": "users/user/jobs/job/original/b.pdf"},
            ],
        ),
        httpx.Response(200, json={}),
        httpx.Response(200, json=[{"name": "users/user/jobs/job/original/c.pdf"}]),
        httpx.Response(200, json={}),
        httpx.Response(200, json=[]),
        httpx.Response(
            200,
            json=[
                {"name": "users/user/jobs/job/remediated/result.pdf"},
                {"name": "users/user/jobs/job/report/report.json"},
            ],
        ),
        httpx.Response(200, json={}),
        httpx.Response(200, json=[]),
    ]
    recorder = Recorder(responses)
    store = SupabaseArtifactStore(
        BASE_URL,
        SECRET,
        "trial-originals",
        "trial-results",
        project_ref="trial-project",
        transport=httpx.MockTransport(recorder.handler),
        list_page_size=2,
    )

    store.delete_job("user", "job")

    list_requests = [request for request in recorder.requests if request.method == "POST"]
    delete_requests = [request for request in recorder.requests if request.method == "DELETE"]
    assert [str(request.url) for request in list_requests] == [
        "https://trial-project.supabase.co/storage/v1/object/list/trial-originals",
        "https://trial-project.supabase.co/storage/v1/object/list/trial-originals",
        "https://trial-project.supabase.co/storage/v1/object/list/trial-originals",
        "https://trial-project.supabase.co/storage/v1/object/list/trial-results",
        "https://trial-project.supabase.co/storage/v1/object/list/trial-results",
    ]
    assert [_json_body(request) for request in list_requests] == [
        {"prefix": "users/user/jobs/job/", "limit": 2, "offset": 0},
        {"prefix": "users/user/jobs/job/", "limit": 2, "offset": 0},
        {"prefix": "users/user/jobs/job/", "limit": 2, "offset": 0},
        {"prefix": "users/user/jobs/job/", "limit": 2, "offset": 0},
        {"prefix": "users/user/jobs/job/", "limit": 2, "offset": 0},
    ]
    assert [str(request.url) for request in delete_requests] == [
        "https://trial-project.supabase.co/storage/v1/object/trial-originals",
        "https://trial-project.supabase.co/storage/v1/object/trial-originals",
        "https://trial-project.supabase.co/storage/v1/object/trial-results",
    ]
    assert _json_body(delete_requests[0]) == {
        "prefixes": [
            "users/user/jobs/job/original/a.pdf",
            "users/user/jobs/job/original/b.pdf",
        ]
    }
    assert _json_body(delete_requests[1]) == {
        "prefixes": ["users/user/jobs/job/original/c.pdf"]
    }
    assert _json_body(delete_requests[2]) == {
        "prefixes": [
            "users/user/jobs/job/remediated/result.pdf",
            "users/user/jobs/job/report/report.json",
        ]
    }


def test_delete_job_rejects_malicious_list_entry_without_batch_delete() -> None:
    recorder = Recorder(
        [
            httpx.Response(200, json=[{"name": "users/other/jobs/job/original/a.pdf"}]),
        ]
    )
    store = _store(recorder)

    with pytest.raises(ArtifactStoreError):
        store.delete_job("user", "job")

    assert [request.method for request in recorder.requests] == ["POST"]


def test_delete_job_caps_pages_and_deletes_more_than_one_thousand_objects() -> None:
    prefix = "users/user/jobs/job/"
    first_page = [
        {"name": f"{prefix}original/{index}.pdf"} for index in range(1000)
    ]
    second_page = [
        {"name": f"{prefix}original/{index}.pdf"} for index in range(1000, 1005)
    ]
    recorder = Recorder(
        [
            httpx.Response(200, json=first_page),
            httpx.Response(200, json={}),
            httpx.Response(200, json=second_page),
            httpx.Response(200, json={}),
            httpx.Response(200, json=[]),
            httpx.Response(200, json=[]),
        ]
    )
    store = SupabaseArtifactStore(
        BASE_URL,
        SECRET,
        "trial-originals",
        "trial-results",
        project_ref="trial-project",
        transport=httpx.MockTransport(recorder.handler),
        list_page_size=5000,
    )

    store.delete_job("user", "job")

    list_bodies = [
        _json_body(request)
        for request in recorder.requests
        if request.method == "POST"
    ]
    delete_bodies = [
        _json_body(request)
        for request in recorder.requests
        if request.method == "DELETE"
    ]
    assert all(body["limit"] == 1000 and body["offset"] == 0 for body in list_bodies)
    assert [len(body["prefixes"]) for body in delete_bodies] == [1000, 5]


def test_delete_job_stops_when_delete_makes_no_progress() -> None:
    page = [{"name": "users/user/jobs/job/original/a.pdf"}]
    recorder = Recorder(
        [
            httpx.Response(200, json=page),
            httpx.Response(200, json={}),
            httpx.Response(200, json=page),
        ]
    )
    store = _store(recorder)

    with pytest.raises(ArtifactStoreError, match="progress"):
        store.delete_job("user", "job")

    assert [request.method for request in recorder.requests] == ["POST", "DELETE", "POST"]


def test_custom_timeouts_are_applied_to_owned_client() -> None:
    store = SupabaseArtifactStore(
        BASE_URL,
        SECRET,
        "trial-originals",
        "trial-results",
        project_ref="trial-project",
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        connect_timeout=1.0,
        read_timeout=2.0,
        write_timeout=3.0,
        pool_timeout=4.0,
    )

    assert store._client.timeout.connect == 1.0
    assert store._client.timeout.read == 2.0
    assert store._client.timeout.write == 3.0
    assert store._client.timeout.pool == 4.0


def test_close_and_context_manager_close_only_owned_client() -> None:
    owned = _store(Recorder())
    with owned as entered:
        assert entered is owned
    assert owned._client.is_closed

    injected = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    store = SupabaseArtifactStore(
        BASE_URL,
        SECRET,
        "trial-originals",
        "trial-results",
        project_ref="trial-project",
        client=injected,
    )
    store.close()
    store.close()
    assert not injected.is_closed
    injected.close()
