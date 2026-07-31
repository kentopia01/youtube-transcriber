from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app
from app.services.mutation_audit import list_mutations, sanitize_actor


def _mutation_client():
    app = create_app()

    @app.post("/_test-mutation")
    async def mutate():
        return {"changed": True}

    return TestClient(app)


def test_cross_site_browser_mutations_are_blocked_and_same_origin_is_allowed(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(settings, "mutation_audit_path", str(audit_path))
    client = _mutation_client()

    blocked = client.post(
        "/_test-mutation",
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    allowed = client.post(
        "/_test-mutation",
        headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"},
    )
    proxied = client.post(
        "/_test-mutation",
        headers={
            "Host": "reader.tailnet.example",
            "Origin": "https://reader.tailnet.example",
            "Sec-Fetch-Site": "same-origin",
            "X-Forwarded-Proto": "https",
        },
    )
    cli = client.post("/_test-mutation", headers={"X-YT-Actor": "openclaw"})

    assert blocked.status_code == 403
    assert allowed.status_code == 200
    assert proxied.status_code == 200
    assert cli.status_code == 200
    records = list_mutations(limit=10)
    assert [record["status_code"] for record in records] == [200, 200, 200, 403]
    assert records[0]["actor"] == "openclaw"
    assert all("body" not in record for record in records)


def test_audit_actor_and_security_headers_are_sanitized(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mutation_audit_path", str(tmp_path / "audit.jsonl"))
    client = _mutation_client()
    response = client.post("/_test-mutation", headers={"X-YT-Actor": "bad actor / secret"})

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert sanitize_actor("bad actor / secret") == "local-api"
    assert list_mutations(limit=1)[0]["actor"] == "local-api"


def test_deployment_contract_is_loopback_non_reload_and_restartable():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    compose = (root / "docker-compose.yml").read_text()

    assert "--reload" not in dockerfile
    for port in ("5432", "6379", "8000"):
        assert f'127.0.0.1:{port}:{port}' in compose
    assert compose.count("restart: unless-stopped") >= 3
    assert "audit_data:/data/audit" in compose


def test_backup_and_restore_scripts_keep_restore_isolated():
    root = Path(__file__).resolve().parents[1]
    backup = (root / "scripts" / "backup_local.sh").read_text()
    restore = (root / "scripts" / "verify_restore_local.sh").read_text()

    assert "pg_dump" in backup and "--format=custom" in backup
    assert "pg_restore" in restore
    assert "shasum -a 256 -c SHA256SUMS" in restore
    assert "yt_restore_verify_" in restore
    assert "dropdb" in restore
    assert "transcriber" not in restore.split("VERIFY_DB=", 1)[1].splitlines()[0]


def test_search_model_work_is_kept_off_the_web_event_loop():
    root = Path(__file__).resolve().parents[1]

    for router in ("search.py", "global_search.py"):
        source = (root / "app" / "routers" / router).read_text()
        assert "from starlette.concurrency import run_in_threadpool" in source
        assert "await run_in_threadpool(" in source
