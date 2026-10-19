import asyncio
import sqlite3

import httpx
import pytest

from gateway import main, mcp_server
from gateway.delivery import delivery_urls
from gateway.mcp_server import PresentationJobs
from test_security_delivery import KEY_A, KEY_B, balance, make_delivery, manager


def _headers(key=KEY_A):
    return {"Authorization": "Bearer " + key}


async def _finish_tasks(jobs):
    while jobs.tasks:
        await asyncio.gather(*list(jobs.tasks))


def test_rest_create_status_idempotency_and_ownership(manager, monkeypatch):
    async def scenario():
        jobs = PresentationJobs(manager)
        release = asyncio.Event()

        async def controlled_failure(job_id, arguments):
            jobs.progress[job_id] = {"percent": 41, "stage": "generating", "message": "生成第2页"}
            await release.wait()
            await manager.cancel_refund(job_id, "controlled failure")

        monkeypatch.setattr(jobs, "execute", controlled_failure)
        monkeypatch.setattr(main, "mcp_jobs", jobs)
        transport = httpx.ASGITransport(app=main.app)
        payload = {"source": "客户原始内容", "template_id": "auto", "slide_count": 5,
                   "request_id": "rest-create-01"}
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            first = await client.post("/api/jobs", headers=_headers(), json=payload)
            assert first.status_code == 200
            job_id = first.json()["job_id"]

            duplicate = await client.post("/api/jobs", headers=_headers(), json=payload)
            assert duplicate.status_code == 200
            assert duplicate.json()["job_id"] == job_id
            changed = await client.post("/api/jobs", headers=_headers(),
                                        json={**payload, "source": "另一份内容"})
            assert changed.status_code == 409

            status = await client.get(f"/api/jobs/{job_id}", headers=_headers())
            assert status.status_code == 200
            assert status.json()["stage"] == "generating"
            assert status.json()["request"] == {"source": "客户原始内容", "template_id": "auto", "slide_count": 5}
            assert (await client.get(f"/api/jobs/{job_id}", headers=_headers(KEY_B))).status_code == 404
            assert (await client.get(f"/api/jobs/{job_id}")).status_code == 401
            assert (await client.get(f"/api/jobs/{job_id}/artifacts", headers=_headers())).status_code == 409

        assert balance(manager) == (1940, 60)
        release.set()
        await _finish_tasks(jobs)
        assert balance(manager) == (2000, 0)

    asyncio.run(scenario())


def test_rest_failed_retry_uses_persisted_request_and_is_idempotent(manager, monkeypatch):
    async def scenario():
        jobs = PresentationJobs(manager)
        attempts = []

        async def fail(job_id, arguments):
            attempts.append((job_id, dict(arguments)))
            await manager.cancel_refund(job_id, "compile failed")

        monkeypatch.setattr(jobs, "execute", fail)
        monkeypatch.setattr(main, "mcp_jobs", jobs)
        transport = httpx.ASGITransport(app=main.app)
        payload = {"source": "需要重试的原文", "template_id": "auto", "slide_count": 7,
                   "request_id": "rest-original-01"}
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            created = await client.post("/api/jobs", headers=_headers(), json=payload)
            original = created.json()["job_id"]
            await _finish_tasks(jobs)

            same_id = await client.post(f"/api/jobs/{original}/retry", headers=_headers(),
                                        json={"request_id": payload["request_id"]})
            assert same_id.status_code == 409
            retried = await client.post(f"/api/jobs/{original}/retry", headers=_headers(),
                                        json={"request_id": "rest-retry-0001"})
            assert retried.status_code == 200
            retry_job = retried.json()["job_id"]
            assert retry_job != original
            await _finish_tasks(jobs)

            duplicate = await client.post(f"/api/jobs/{original}/retry", headers=_headers(),
                                          json={"request_id": "rest-retry-0001"})
            assert duplicate.status_code == 200
            assert duplicate.json()["job_id"] == retry_job
            assert (await client.post(f"/api/jobs/{original}/retry", headers=_headers(KEY_B),
                                      json={"request_id": "other-retry-01"})).status_code == 404

        assert [entry[1] for entry in attempts] == [
            {"source": "需要重试的原文", "template_id": "auto", "slide_count": 7},
            {"source": "需要重试的原文", "template_id": "auto", "slide_count": 7},
        ]
        assert balance(manager) == (2000, 0)
        with sqlite3.connect(manager.db_path) as db:
            assert db.execute("SELECT count(*) FROM credit_ledger WHERE action='FREEZE'").fetchone()[0] == 2
            assert db.execute("SELECT count(*) FROM credit_ledger WHERE action='REFUND'").fetchone()[0] == 2

    asyncio.run(scenario())


def test_rest_read_scope_capabilities_and_verified_artifacts(manager, monkeypatch):
    async def scenario():
        jobs = PresentationJobs(manager)
        monkeypatch.setattr(main, "mcp_jobs", jobs)
        job_id = "ppt_1234567890"
        await manager.try_freeze_credits(KEY_A, job_id, "ppt", "test", 60)
        spec, manifest = make_delivery(manager.jobs_root / job_id / "output", job=job_id)
        spec["_request"] = {"source": "test", "template_id": "auto", "slide_count": 2}
        await manager.save_compiled_spec(job_id, spec)
        await manager.confirm_settle(job_id, .1, delivery_urls(job_id, manifest))

        read_key = "test-read-" + "r" * 40
        with sqlite3.connect(manager.db_path) as db:
            db.execute("INSERT INTO mcp_api_keys(api_key,user_id,created_at,scope) VALUES (?,?,?,?)",
                       (read_key, "a", "now", "read"))
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            read_session = await client.get("/api/session", headers=_headers(read_key))
            assert read_session.json()["scope"] == "read"
            assert read_session.json()["can_generate"] is False
            generate_session = await client.get("/api/session", headers=_headers())
            assert generate_session.json()["scope"] == "generate"
            assert generate_session.json()["can_generate"] is True
            caps = await client.get("/api/capabilities", headers=_headers(read_key))
            assert caps.status_code == 200
            assert caps.json()["delivery_modes"]["ppt"] == {
                "supported": True, "freeze_credits": 60, "progress": True,
                "preview_after_validation": True, "retry": True,
                "execution_modes": ["codex_cli"],
            }
            assert caps.json()["delivery_modes"]["video"]["supported"] is True
            assert caps.json()["partial_preview"] is False
            assert (await client.get(f"/api/jobs/{job_id}", headers=_headers(read_key))).status_code == 200
            artifacts = await client.get(f"/api/jobs/{job_id}/artifacts", headers=_headers(read_key))
            assert artifacts.status_code == 200
            assert artifacts.json()["file_status"] == "PASSED"
            denied = await client.post("/api/jobs", headers=_headers(read_key), json={
                "source": "cannot generate", "request_id": "read-scope-01", "slide_count": 2})
            assert denied.status_code == 403
            before = balance(manager)
            legacy_denied = await client.post("/api/jobs/stream", headers=_headers(read_key), json={
                "prompt_cn": "cannot bypass scope", "slide_count": 2})
            assert legacy_denied.status_code == 403
            assert balance(manager) == before

    asyncio.run(scenario())


def test_admission_cancellation_after_freeze_refunds_immediately(manager, monkeypatch):
    async def scenario():
        jobs = PresentationJobs(manager)
        persisted = asyncio.Event()

        async def blocked_save(job_id, spec):
            persisted.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(manager, "save_compiled_spec", blocked_save)
        request = asyncio.create_task(jobs.create(
            {"user_id": "a", "api_key": KEY_A, "scope": "generate"},
            "admission cancellation", "auto", 2, "cancel-admit-01"))
        await asyncio.wait_for(persisted.wait(), 1)
        assert balance(manager) == (1940, 60)
        await jobs.close()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert balance(manager) == (2000, 0)
        with sqlite3.connect(manager.db_path) as db:
            row = db.execute("SELECT status,error_msg FROM media_jobs").fetchone()
            assert row[0] == "FAILED"
            assert "admission" in row[1]

    asyncio.run(scenario())


def test_async_worker_read_timeout_matches_legacy_limit(manager, monkeypatch):
    async def scenario():
        jobs = PresentationJobs(manager)
        job_id = "ppt_6000000000"
        await manager.try_freeze_credits(KEY_A, job_id, "ppt", "timeout test", 60)
        observed = []

        async def compile_spec(*args, **kwargs):
            return {"slide_count": 2, "slide_outline": [{}, {}]}

        class Stream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                yield 'data: {"type":"error","message":"controlled"}'

        class Client:
            def __init__(self, *, timeout, **kwargs):
                observed.append(timeout)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            def stream(self, *args, **kwargs):
                return Stream()

        monkeypatch.setattr(mcp_server, "compile_cn_request_to_english_spec", compile_spec)
        monkeypatch.setattr(mcp_server.httpx, "AsyncClient", Client)
        await jobs.execute(job_id, {"source": "timeout test", "template_id": "auto", "slide_count": 2})
        assert observed[0].connect == 15
        assert observed[0].read == 600
        assert balance(manager) == (2000, 0)

    asyncio.run(scenario())
