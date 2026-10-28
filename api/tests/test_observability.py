from __future__ import annotations

import json
import logging

from pydantic import SecretStr

from voix_api.config import Settings
from voix_api.observability import JsonFormatter, _request_id

from .conftest import voice_id


def test_request_id_generated_echoed_and_in_errors(client):
    resp = client.get("/v1/jobs")  # 401
    rid = resp.headers["x-request-id"]
    assert len(rid) == 32 and resp.json()["request_id"] == rid

    mine = client.get("/healthz", headers={"X-Request-ID": "trace-abc-12345"})
    assert mine.headers["x-request-id"] == "trace-abc-12345"
    junk = client.get("/healthz", headers={"X-Request-ID": "bad id\nwith newline"})
    assert junk.headers["x-request-id"] != "bad id\nwith newline"


def test_security_headers(client):
    h = client.get("/healthz").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert h["content-security-policy"].startswith("default-src 'none'")
    assert "strict-transport-security" not in h  # only in production
    assert "content-security-policy" not in client.get("/docs").headers  # Swagger UI loads its assets


def test_metrics_exposes_http_and_job_metrics(client, user):
    client.post(
        "/v1/jobs/tts",
        json={"text": "Hi there.", "voice_id": voice_id(client, user["headers"])},
        headers=user["headers"],
    )
    body = client.get("/metrics").text
    assert 'http_requests_total{method="POST",route="/v1/jobs/tts",status="202"}' in body
    assert 'voix_jobs_created_total{engine="mock",type="synthesize"}' in body
    assert 'voix_queue_depth{engine="mock"} 1.0' in body
    assert "voix_workers_online 0.0" in body
    # route templates, not raw paths: no job ids in label values
    assert "/v1/jobs/{job_id}" not in body or "-" not in body.split("/v1/jobs/{job_id}")[0][-40:]


def test_metrics_token(client, settings):
    settings.metrics_token = SecretStr("s3cret")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_json_log_line_carries_request_id():
    token = _request_id.set("rid-0001-abcd")
    try:
        record = logging.makeLogRecord(
            {"name": "x", "levelname": "INFO", "msg": "hello %s", "args": ("you",), "route": "/v1/x"}
        )
        line = json.loads(JsonFormatter().format(record))
    finally:
        _request_id.reset(token)
    assert line["msg"] == "hello you" and line["request_id"] == "rid-0001-abcd" and line["route"] == "/v1/x"


def test_hosted_postgres_urls_are_normalised():
    assert Settings(database_url="postgres://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url="postgresql://u:p@h/db").database_url == "postgresql+psycopg://u:p@h/db"
    assert Settings(database_url="sqlite:///x.db").database_url == "sqlite:///x.db"
