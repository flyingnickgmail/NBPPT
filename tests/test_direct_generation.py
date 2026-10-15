import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image
import pytest

from gateway.deepseek_compiler import compile_cn_request_to_english_spec, validate_direct_completion
from worker import direct_generation as direct
from worker.oss_uploader import upload_job_artifacts_to_cdn


def spec(count=5):
    return {"original_prompt_cn": "第一条原文依据。第二条事实。第三条是方向。截图共42页，不是生成页数。",
            "slide_count": count, "task_summary_cn": "客户洞察", "matched_template": {"id": "yonyou-ci-bg"}}


def plan(count=5):
    titles = ["理解客户", "总部视角", "区域差异", "门店辅导", "未来闭环"]
    return {"task_summary_cn": "客户洞察", "slide_outline": [
        {"slide_num": i + 1, "action_title_cn": titles[i], "key_message_cn": titles[i] + "独立论点",
         "page_type": ["diagram", "chart", "comparison", "swimlane", "roadmap"][i],
         "visible_text_cn": titles[i] + "，仍需验证", "layout_description": "按证据布置图表",
         "source_quotes": ["第一条原文依据。"], "evidence_status": "direction"}
        for i in range(count)]}


def fixture_output(root, count=5):
    assets = root / "output/assets"
    assets.mkdir(parents=True)
    for i in range(1, count + 1):
        Image.new("RGB", (1280, 720), (i * 30, 20, 50)).save(assets / f"slide_preview_{i}.png")
    (root / "deck_plan.json").write_text(json.dumps(plan(count)))
    (root / "review.json").write_text(json.dumps({"reviewed_pages": list(range(1, count+1)), "issues": []}))
    return assets


def test_direct_contract_preserves_source_and_skips_planner(monkeypatch):
    monkeypatch.setattr("gateway.deepseek_compiler.get_runtime_settings", lambda: pytest.fail("no separate planner"))
    source = spec()["original_prompt_cn"]
    result = asyncio.run(compile_cn_request_to_english_spec(source, "ppt", {"slide_count": 0}))
    assert result["generation_contract"] == "skill-direct-v1"
    assert result["original_prompt_cn"] == source
    assert result["slide_count"] == 0 and result["slide_outline"] == []
    assert "12-18%" not in json.dumps(result)


def test_prompt_uses_skills_and_varied_layouts():
    prompt = direct.build_prompt(spec())
    assert "SKILL.md" in prompt and "source.md IN FULL" in prompt
    assert "not one repeated page skeleton" in prompt
    assert "EXACT path returned" in prompt
    assert "Exactly 5 pages" in prompt


@pytest.mark.parametrize("mutation", ["duplicate_title", "duplicate_argument", "no_evidence", "made_up_quote", "same_layout", "missing_page", "bad_number"])
def test_bad_plans_rejected(mutation):
    value = plan()
    slides = value["slide_outline"]
    if mutation == "duplicate_title": slides[1]["action_title_cn"] = slides[0]["action_title_cn"]
    if mutation == "duplicate_argument": slides[1]["key_message_cn"] = slides[0]["key_message_cn"]
    if mutation == "no_evidence": slides[0]["source_quotes"] = []
    if mutation == "made_up_quote": slides[0]["source_quotes"] = ["收益提升50%"]
    if mutation == "same_layout":
        for slide in slides: slide["page_type"] = "cards"
    if mutation == "missing_page": slides.pop()
    if mutation == "bad_number": slides[0]["slide_num"] = 2
    with pytest.raises(ValueError): direct.validate_plan(value, spec())


@pytest.mark.parametrize("mutation", ["missing", "extra", "corrupt", "small", "portrait", "duplicate", "symlink", "unreviewed"])
def test_bad_artifacts_rejected(tmp_path, mutation):
    assets = fixture_output(tmp_path)
    first = assets / "slide_preview_1.png"
    if mutation == "missing": first.unlink()
    if mutation == "extra": Image.new("RGB", (1280,720)).save(assets / "unrelated.png")
    if mutation == "corrupt": first.write_bytes(b"not an image")
    if mutation == "small": Image.new("RGB", (128,72)).save(first)
    if mutation == "portrait": Image.new("RGB", (1280,2000)).save(first)
    if mutation == "duplicate": (assets / "slide_preview_2.png").write_bytes(first.read_bytes())
    if mutation == "symlink":
        first.unlink(); first.symlink_to(assets / "slide_preview_2.png")
    if mutation == "unreviewed": (tmp_path / "review.json").write_text('{"reviewed_pages":[],"issues":[]}')
    with pytest.raises((ValueError, OSError)): direct.package_deck("test", tmp_path, spec())


def test_package_reopens_deck_and_orders_previews(tmp_path):
    fixture_output(tmp_path)
    source_plan = plan()
    source_plan["task_summary_cn"] = "A & B <script>alert(1)</script>"
    (tmp_path / "deck_plan.json").write_text(json.dumps(source_plan))
    actual, qa = direct.package_deck("test", tmp_path, spec())
    assert actual["task_summary_cn"] == source_plan["task_summary_cn"]
    html_deck = (tmp_path / "output/test_deck_interactive.html").read_text()
    assert "<title>A &amp; B &lt;script&gt;" in html_deck
    assert "<script>alert(1)</script>" not in html_deck
    assert actual["slide_count"] == 5 and qa["status"] == "PASSED"
    assert len(qa["layout_families"]) == 5
    urls = upload_job_artifacts_to_cdn("test", tmp_path / "output")
    assert urls["pptx_url"] and urls["html_deck_url"]
    # Page ten must follow page nine, not page one.
    for n in range(6,13): (tmp_path / f"output/assets/slide_preview_{n}.png").touch()
    urls = upload_job_artifacts_to_cdn("test", tmp_path / "output")
    assert urls["slide_preview_urls"][9].endswith("slide_preview_10.png")


def test_failed_cli_never_completes_or_falls_back(tmp_path):
    async def run():
        req = SimpleNamespace(job_id="failed", english_spec=spec(), runtime_keys={})
        return [json.loads(e[6:]) async for e in direct.generate_deck_stream(req, tmp_path, "/usr/bin/false", asyncio.Semaphore(1))]
    events = asyncio.run(run())
    assert events[-1]["type"] == "error"
    assert not any(e["type"] == "completed" for e in events)
    assert not list(tmp_path.rglob("*.pptx"))


def test_empty_successful_cli_does_not_complete(tmp_path):
    async def run():
        req = SimpleNamespace(job_id="empty", english_spec=spec(), runtime_keys={})
        return [json.loads(e[6:]) async for e in direct.generate_deck_stream(req, tmp_path, "/usr/bin/true", asyncio.Semaphore(1))]
    assert asyncio.run(run())[-1]["type"] == "error"


def test_existing_job_never_reused(tmp_path):
    (tmp_path / "existing").mkdir()
    async def run():
        req = SimpleNamespace(job_id="existing", english_spec=spec(), runtime_keys={})
        return [json.loads(e[6:]) async for e in direct.generate_deck_stream(req, tmp_path, "/usr/bin/true", asyncio.Semaphore(1))]
    assert asyncio.run(run())[-1]["type"] == "error"


def test_failed_legacy_planner_does_not_return_sample(monkeypatch):
    monkeypatch.setattr("gateway.deepseek_compiler.get_runtime_settings", lambda: {})
    with pytest.raises(RuntimeError, match="未生成替代内容"):
        asyncio.run(compile_cn_request_to_english_spec("客户原文", "ppt", {"execution_mode": "claude_cli"}))


@pytest.mark.parametrize("worker_status", ["PASSED", "PARTIAL", "error"])
def test_gateway_saves_actual_plan_and_only_settles_passed(monkeypatch, worker_status):
    from gateway import main
    actual = {**spec(), **plan(), "generation_contract": "skill-direct-v1"}
    billing = SimpleNamespace(
        try_freeze_credits=AsyncMock(return_value={"balance_after_freeze": 100}),
        save_compiled_spec=AsyncMock(), cancel_refund=AsyncMock(return_value={}),
        confirm_settle=AsyncMock(return_value={"charged_credits": 10, "refunded_diff_credits": 50, "overseas_cost_usd": 0.4}))
    monkeypatch.setattr(main, "billing", billing)
    monkeypatch.setattr(main, "get_runtime_settings", lambda: {"overseas_worker_url": "http://worker", "overseas_worker_secret": "test"})
    class Stream:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def raise_for_status(self): pass
        async def aiter_lines(self):
            if worker_status == "error":
                yield 'data: {"type":"error","message":"generation failed"}'
            else:
                yield "data: " + json.dumps({"type": "completed", "compiled_spec": actual,
                    "qa_report": {"status": worker_status, "planned_slides":5, "delivered_slides":5, "pptx_slides_count":5},
                    "cdn_urls": {"pptx_url":"/test.pptx", "html_deck_url":"/test.html", "slide_preview_urls":[f"/{i}.png" for i in range(5)]}, "total_cost_usd": 0.4})
    class Client(Stream):
        def __init__(self, **kwargs): pass
        def stream(self, *args, **kwargs): return Stream()
    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    async def run():
        response = await main.stream_create_job(main.CreateJobRequest(prompt_cn=spec()["original_prompt_cn"], slide_count=5))
        return [json.loads(msg[6:]) async for msg in response.body_iterator]
    events = asyncio.run(run())
    if worker_status == "PASSED":
        assert events[-1]["type"] == "completed"
        assert events[-1]["en_spec"]["slide_outline"] == actual["slide_outline"]
        assert billing.save_compiled_spec.await_count == 2
        billing.confirm_settle.assert_awaited_once()
        billing.cancel_refund.assert_not_awaited()
    else:
        assert events[-1]["type"] == "error"
        billing.confirm_settle.assert_not_awaited()
        billing.cancel_refund.assert_awaited_once()


def test_empty_completed_report_cannot_settle():
    with pytest.raises(RuntimeError, match="完整交付检查"):
        validate_direct_completion({"compiled_spec": plan(), "qa_report": {"status": "PASSED"}, "cdn_urls": {}})
