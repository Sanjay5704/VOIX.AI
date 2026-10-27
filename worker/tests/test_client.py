from __future__ import annotations

import httpx
import pytest

from voix_worker.client import ApiUnavailable, LeaseLost, WorkerClient


def _client(handler, retries=3) -> WorkerClient:
    http = httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(handler))
    return WorkerClient(http, "w1", ["mock"], max_retries=retries, backoff_base=0.001, backoff_cap=0.001)


def test_retries_transient_errors_then_succeeds():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 1:
            raise httpx.ConnectError("wifi dropped")
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"id": "j1", "type": "synthesize"})

    assert _client(handler).claim()["id"] == "j1"
    assert len(calls) == 3


def test_gives_up_after_max_retries():
    with pytest.raises(ApiUnavailable):
        _client(lambda r: httpx.Response(502), retries=2).register()


def test_204_means_no_job():
    assert _client(lambda r: httpx.Response(204)).claim() is None


def test_409_is_lease_lost_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(409, json={"error": {"code": "lease_lost"}})

    with pytest.raises(LeaseLost):
        _client(handler).heartbeat("j1", 0.5)
    assert len(calls) == 1


def test_client_errors_are_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401)

    with pytest.raises(httpx.HTTPStatusError):
        _client(handler).register()
    assert len(calls) == 1


def test_multipart_body_is_resent_intact_on_retry(tmp_path):
    f = tmp_path / "out.mp3"
    f.write_bytes(b"AUDIO-BYTES")
    bodies = []

    def handler(request):
        bodies.append(request.read())
        return httpx.Response(503) if len(bodies) == 1 else httpx.Response(200, json={"status": "succeeded"})

    assert _client(handler).complete("j1", {"format": "mp3"}, {"audio": f})["status"] == "succeeded"
    assert b"AUDIO-BYTES" in bodies[0] and b"AUDIO-BYTES" in bodies[1]
