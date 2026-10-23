from fastapi.testclient import TestClient
from PIL import Image

import tools.report_studio.app as application
from tools.report_studio.models import ExportInput
from tools.report_studio.overview import attach


def test_web_continuation_skips_initial_generation_and_clears_stale_image(tmp_path, monkeypatch):
    data = ExportInput.model_validate_json((application.ROOT / 'sample.json').read_text())
    image = tmp_path / 'old.png'
    Image.new('RGB', (40, 50)).save(image)
    data = attach(data, image, '原报告的旧全景图片，继续复审后不能继续使用旧版本图片。')
    before = data.model_dump()
    stages = []

    async def forbidden(*args):
        raise AssertionError('继续操作不应重新生成初稿')

    async def refine(report, content):
        stages.append('refine')
        assert content == data.content
        result = report.model_copy(deep=True)
        result.sections[0].paragraphs[0] = '修订后的说明仍然只依据输入材料。'
        return result

    async def reading(report, content):
        stages.append('reading')
        return report

    async def editorial(report, content):
        raise AssertionError('独立全景图负责封面，不应重复调用旧封面设计拖住正文')

    for name, function in [('ai_report', forbidden), ('refine_report', refine), ('design_reading', reading), ('design_editorial', editorial)]:
        monkeypatch.setattr(application, name, function)
    with TestClient(application.app) as client:
        response = client.post('/api/continue', json=data.model_dump())
        assert response.status_code == 200
        result = response.json()
        assert result['overview'] is None and result['mode'] == 'ai'
        assert result['report']['sources'] == before['report']['sources']
        assert result['report']['metrics'] == before['report']['metrics']
        assert stages == ['refine', 'reading']
        assert data.model_dump() == before
        assert not application.lock.locked()
        assert client.post('/api/continue', json=data.model_dump(), headers={'Origin': 'https://example.org'}).status_code == 403


def test_invalid_import_is_rejected_before_model_use(monkeypatch):
    data = ExportInput.model_validate_json((application.ROOT / 'sample.json').read_text())
    data.report.metrics[0].quote = '材料中不存在的引文99999'

    async def forbidden(*args):
        raise AssertionError('无效输入不能进入模型')

    monkeypatch.setattr(application, 'refine_report', forbidden)
    with TestClient(application.app) as client:
        assert client.post('/api/continue', json=data.model_dump()).status_code == 422
