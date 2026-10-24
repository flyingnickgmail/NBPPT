"""Test-only application entry points. No route or switch is added to production.

The worker's paid model turn is replaced; routing, SSE, storage, artifact
validation and billing are the production implementations in separate processes.
"""
import asyncio
import os
import random
from pathlib import Path

if not os.environ.get('NBPPT_DEPLOYMENT_TEST_ROOT'):
    raise RuntimeError('Only load this entry point from the deployment test')

from PIL import Image
from gateway import main, reports
from tools.report_studio.models import ExportInput
from tools.report_studio.overview import attach
from worker import report_generation, worker_api


async def replay_model(data, kind, folder, progress, **kwargs):
    await progress('generating', 'Synthetic deployment fixture; no model call')
    await asyncio.sleep(.05)
    if data.content.startswith('DEPLOYMENT_FIXTURE_FAILURE'):
        raise ValueError('Controlled test failure')
    if kind == 'generate':
        result = ExportInput.model_validate_json((reports.STATIC.parent / 'sample.json').read_text())
        result.content = data.content
        result.report.title = data.title or '部署验收合成材料'
        result.theme = data.theme
    else:
        result = data.model_copy(deep=True)
    result.mode = 'ai'
    if kind == 'overview':
        # Valid, incompressible PNG: the embedded request exceeds the old 1 MB
        # nginx limit. A flat-color image would silently miss that regression.
        image = folder / 'fixture.png'
        Image.frombytes('RGB', (800, 1000), random.Random(20261025).randbytes(2_400_000)).save(image)
        result = attach(result, image, '合成随机像素仅验证大图片传输、报告绑定与下载一致性，不代表业务内容或美术验收。')
    return result


runtime = {'overseas_worker_url': os.environ['OVERSEAS_WORKER_URL'],
           'overseas_worker_secret': os.environ['OVERSEAS_WORKER_SECRET']}
reports.get_runtime_settings = lambda: runtime
report_generation.generate_report = replay_model
gateway = main.app
worker = worker_api.app
