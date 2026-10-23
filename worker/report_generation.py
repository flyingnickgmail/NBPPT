"""Trusted report orchestration; only model turns enter the per-job sandbox."""
import asyncio
import base64
import json
import shutil

from gateway.report_contract import parse_input, inspect_report
from gateway.delivery import delivery_urls
from tools.report_studio.models import ExportInput
from tools.report_studio.app import export_html
from tools.report_studio.generator import ai_report, refine_report, design_reading, design_editorial
from tools.report_studio.overview_generation import create_overview
from tools.report_studio.runtime import worker_runtime


async def generate_report(data, kind, folder, progress):
    if kind == 'overview':
        data.overview = None
        return await create_overview(data, folder, progress)
    if kind == 'continue':
        data.overview = None
        data.report = await refine_report(data.report, data.content)
        data.report = await design_reading(data.report, data.content)
        data.mode = 'ai'
        return data
    await progress('generating', '正在核对材料、组织观点与图表')
    report = await ai_report(data.content, data.title)
    if len(data.content) < 12000:
        await progress('composing', '正在编排图表叙事与封面')
        report = await design_reading(report, data.content)
        report = await design_editorial(report, data.content)
    return ExportInput(report=report, content=data.content, mode='ai', theme=data.theme)


async def report_stream(req, jobs_root, binary, semaphore):
    folder = jobs_root / req.job_id
    try:
        folder.mkdir(parents=True, exist_ok=False)
        folder.chmod(0o750)
    except FileExistsError:
        yield 'data: ' + json.dumps({'type': 'error', 'message': '任务目录已存在，请查询原任务'}) + '\n\n'
        return
    queue = asyncio.Queue()

    async def progress(state, message, **extra):
        await queue.put({'type': 'progress', 'stage': state, 'message_cn': message})

    async def execute():
        async with semaphore:
            with worker_runtime(folder, binary):
                data = parse_input(req.spec)
                (folder / 'request.json').write_text(req.model_dump_json(indent=2))
                async with asyncio.timeout(3600):
                    result = await generate_report(data, req.spec['operation'], folder, progress)
                staging = folder / 'staging'
                staging.mkdir()
                (staging / 'report.json').write_text(result.model_dump_json(indent=2))
                (staging / 'report.html').write_text(export_html(result))
                if result.overview:
                    (staging / 'overview.png').write_bytes(base64.b64decode(result.overview.data_url.split(',', 1)[1]))
                task_type = 'report_share' if req.spec['operation'] == 'overview' else 'report'
                manifest = await asyncio.to_thread(inspect_report, req.job_id, task_type, req.spec, staging)
                (staging / 'delivery.json').write_text(json.dumps(manifest, ensure_ascii=False))
                staging.chmod(0o750)
                for artifact in staging.iterdir():
                    artifact.chmod(0o640)
                staging.rename(folder / 'output')
                return {'type': 'completed', 'cdn_urls': delivery_urls(req.job_id, manifest)}

    task = asyncio.create_task(execute())
    try:
        while not task.done():
            event_task = asyncio.create_task(queue.get())
            try:
                done, _ = await asyncio.wait([task, event_task], timeout=15, return_when=asyncio.FIRST_COMPLETED)
                if event_task in done:
                    event = event_task.result()
                elif task in done:
                    break
                else:
                    event = {'type': 'heartbeat'}
            finally:
                if not event_task.done():
                    event_task.cancel()
                await asyncio.gather(event_task, return_exceptions=True)
            yield 'data: ' + json.dumps(event, ensure_ascii=False) + '\n\n'
        yield 'data: ' + json.dumps(await task, ensure_ascii=False) + '\n\n'
    except asyncio.CancelledError:
        raise
    except Exception:
        yield 'data: ' + json.dumps({'type': 'error', 'message': '报告生成或交付校验失败，积分将退回'}, ensure_ascii=False) + '\n\n'
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
