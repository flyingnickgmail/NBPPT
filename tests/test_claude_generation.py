"""Offline Claude routing, isolation and strict delivery tests; no model requests."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from gateway import main
from gateway.deepseek_compiler import compile_cn_request_to_english_spec, validate_direct_completion
from gateway.mcp_server import PresentationJobs
from worker import claude_generation as claude, direct_generation as direct, isolation
from test_direct_generation import fixture_output, plan, spec
from test_security_delivery import KEY_A, balance, manager


def svg(title):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="1672" height="941" viewBox="0 0 1672 941"><rect width="1672" height="941" fill="white"/><text x="60" y="80">{title}</text></svg>'


def test_claude_direct_contract_and_english_instructions(monkeypatch):
    monkeypatch.setenv("NBPPT_CLAUDE_ENABLED", "true")
    monkeypatch.setattr("gateway.deepseek_compiler.get_runtime_settings", lambda: pytest.fail("no legacy planner"))
    value = asyncio.run(compile_cn_request_to_english_spec(spec()["original_prompt_cn"], "ppt", {"slide_count": 5, "execution_mode": "claude_cli"}))
    assert value["generation_contract"] == "skill-direct-v1"
    assert value["generator_engine"] == "claude_cli"
    assert value["original_prompt_cn"] == spec()["original_prompt_cn"]
    prompt = claude.build_prompt(value)
    assert "source-svg-deck/SKILL.md" in prompt
    assert "rsvg-convert" in prompt and "Open EVERY numbered PNG" in prompt
    assert "built-in image_gen" not in prompt
    assert "not a repeated page skeleton" in prompt
    args = claude.command("/usr/bin/claude", prompt, .85)
    assert "--safe-mode" in args and "--no-session-persistence" in args
    assert args[args.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert "--dangerously-skip-permissions" not in args
    assert "Bash(rsvg-convert *)" in args[args.index("--allowedTools") + 1]


@pytest.mark.parametrize("budget", [0, -1, 6, float("nan"), float("inf"), True, "1"])
def test_invalid_budgets_rejected(budget):
    with pytest.raises(ValueError):
        claude.command("/usr/bin/claude", "test", budget)


def test_disabled_provider_rejected_before_freeze(manager, monkeypatch):
    monkeypatch.delenv("NBPPT_CLAUDE_ENABLED", raising=False)
    async def scenario():
        jobs = PresentationJobs(manager)
        monkeypatch.setattr(main, "mcp_jobs", jobs)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="https://test") as client:
            res = await client.post("/api/jobs", headers={"Authorization": "Bearer " + KEY_A}, json={"source": "产品介绍", "slide_count": 2, "execution_mode": "claude_cli", "request_id": "claude-disabled-1"})
            assert res.status_code == 422
        assert balance(manager) == (2000, 0)
        assert not jobs.tasks
    asyncio.run(scenario())


def test_video_cannot_silently_substitute_claude_with_codex(manager, monkeypatch):
    monkeypatch.setenv("NBPPT_CLAUDE_ENABLED", "true")
    async def scenario():
        jobs = PresentationJobs(manager)
        with pytest.raises(ValueError, match="视频尚未开放 Claude"):
            await jobs.create({"user_id": "a", "api_key": KEY_A, "scope": "generate"},
                              "产品介绍", "auto", 0, "claude-video-01", task_type="video", execution_mode="claude_cli")
        assert balance(manager) == (2000, 0)
        assert not jobs.tasks
    asyncio.run(scenario())


def test_claude_retry_keeps_provider_and_refunds(manager, monkeypatch):
    monkeypatch.setenv("NBPPT_CLAUDE_ENABLED", "true")
    async def scenario():
        jobs = PresentationJobs(manager)
        calls = []
        async def fail(job, args):
            calls.append(args)
            await manager.cancel_refund(job, "controlled Claude failure")
        monkeypatch.setattr(jobs, "execute", fail)
        principal = {"user_id": "a", "api_key": KEY_A, "scope": "generate"}
        created = await jobs.create(principal, "产品介绍", "auto", 2, "claude-create-01", execution_mode="claude_cli")
        await asyncio.gather(*list(jobs.tasks))
        with pytest.raises(ValueError):
            await jobs.create(principal, "产品介绍", "auto", 2, "claude-create-01", execution_mode="codex_cli")
        await jobs.retry(principal, created["job_id"], "claude-retry-01")
        await asyncio.gather(*list(jobs.tasks))
        assert len(calls) == 2 and all(a["execution_mode"] == "claude_cli" for a in calls)
        assert balance(manager) == (2000, 0)
    asyncio.run(scenario())


def test_claude_isolation_uses_only_dedicated_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("NBPPT_REQUIRE_ISOLATION", "true")
    monkeypatch.setattr(isolation.sys, "platform", "linux")
    monkeypatch.setattr(isolation.os, "geteuid", lambda: 1001)
    monkeypatch.setattr(isolation.shutil, "which", lambda _: "/usr/bin/bwrap")
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(isolation.Path, "home", classmethod(lambda _: home))
    job = tmp_path / "job"
    job.mkdir()
    with pytest.raises(RuntimeError, match="Dedicated Claude"):
        isolation.isolated_command(["/usr/bin/claude"], job, [], agent="claude")
    auth = home / ".claude/.credentials.json"
    auth.write_text("{}")
    (home / ".claude.json").write_text(json.dumps({"oauthAccount": {"accountUuid": "test"}, "hooks": {"bad": "command"}}))
    args, sandbox = isolation.isolated_command(["/usr/bin/claude"], job, [], agent="claude")
    assert str(auth) in args and "--clearenv" in args
    assert not any(".codex/auth" in x or "/root/" in x for x in args)
    assert "hooks" not in (sandbox / ".claude.json").read_text()
    auth.unlink()
    auth.symlink_to(home / ".claude.json")
    with pytest.raises(RuntimeError, match="Dedicated Claude"):
        isolation.isolated_command(["/usr/bin/claude"], job, [], agent="claude")


@pytest.mark.parametrize("defect", ["missing", "extra", "script", "image", "entity", "external", "bad_size", "wrong_title", "symlink"])
def test_bad_svg_sources_rejected(tmp_path, defect):
    slides = plan(1)["slide_outline"]
    path = tmp_path / "slide_source_1.svg"
    path.write_text(svg(slides[0]["action_title_cn"]))
    if defect == "missing": path.unlink()
    if defect == "extra": (tmp_path / "extra.svg").write_text(path.read_text())
    if defect in ("script", "image"):
        path.write_text(path.read_text().replace("</svg>", f"<{defect}/></svg>"))
    if defect == "entity": path.write_text('<!DOCTYPE svg [<!ENTITY a "bad">]>' + path.read_text())
    if defect == "external": path.write_text(path.read_text().replace('fill="white"', 'fill="url(file:///etc/passwd)"'))
    if defect == "bad_size": path.write_text(path.read_text().replace("1672 941", "1280 720"))
    if defect == "wrong_title": path.write_text(svg("另一个标题"))
    if defect == "symlink":
        other = tmp_path.parent / "outside.svg"
        path.rename(other)
        path.symlink_to(other)
    with pytest.raises(ValueError): claude.validate_svg_sources(tmp_path, slides)


def test_valid_claude_delivery_uses_common_integrity_gate(tmp_path):
    assets = fixture_output(tmp_path)
    for i, slide in enumerate(plan()["slide_outline"], 1):
        (assets / f"slide_source_{i}.svg").write_text(svg(slide["action_title_cn"]))
    actual, qa = direct.package_deck("ppt_c1a0de0001", tmp_path, {**spec(), "generator_engine": "claude_cli"})
    assert actual["generator_engine"] == "claude_cli" and qa["status"] == "PASSED"
    assert len(list((tmp_path / "output").glob("*.pptx"))) == 1


@pytest.mark.parametrize("result", [None, {"type": "result", "subtype": "error_max_budget_usd", "is_error": True}, {"type": "result", "subtype": "success", "is_error": False}])
def test_empty_or_failed_cli_report_cannot_complete(tmp_path, monkeypatch, result):
    monkeypatch.setenv("NBPPT_CLAUDE_ENABLED", "true")
    monkeypatch.setenv("NBPPT_REQUIRE_ISOLATION", "false")
    async def launch(*args, **kwargs):
        if result: kwargs["stdout"].write(json.dumps(result).encode())
        async def wait(): return 0
        return SimpleNamespace(returncode=0, wait=wait)
    monkeypatch.setattr(direct.asyncio, "create_subprocess_exec", launch)
    async def run():
        req = SimpleNamespace(job_id="ppt_c1a0de0002", english_spec={**spec(), "generator_engine": "claude_cli"}, runtime_keys={}, max_budget_usd=.85)
        sem = asyncio.Semaphore(1)
        events = [json.loads(e[6:]) async for e in direct.generate_deck_stream(req, tmp_path, "/codex", sem, "/usr/bin/claude")]
        assert sem._value == 1
        return events
    events = asyncio.run(run())
    assert events[-1]["type"] == "error" and not any(e["type"] == "completed" for e in events)
    assert not list(tmp_path.rglob("*.pptx"))


def test_completion_cannot_change_admitted_provider():
    expected = {**spec(), "generation_contract": "skill-direct-v1", "generator_engine": "claude_cli"}
    event = {"compiled_spec": {**expected, **plan(), "generator_engine": "codex_cli"}, "qa_report": {"status": "PASSED", "planned_slides": 5, "delivered_slides": 5, "pptx_slides_count": 5}, "cdn_urls": {"pptx_url": "/a.pptx", "html_deck_url": "/a.html", "slide_preview_urls": [f"/{i}.png" for i in range(5)]}}
    with pytest.raises((ValueError, RuntimeError)):
        validate_direct_completion(event, expected)
