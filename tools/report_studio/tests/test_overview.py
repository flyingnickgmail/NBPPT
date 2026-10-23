import pytest
from fastapi.testclient import TestClient
from PIL import Image

from tools.report_studio.app import ROOT, app, export_html
from tools.report_studio.models import ExportInput
from tools.report_studio.overview import attach, image_brief, validate_overview
from tools.report_studio.overview_models import OverviewImage


@pytest.fixture
def data():
    return ExportInput.model_validate_json((ROOT / 'sample.json').read_text())


def test_image_roundtrip_is_portable_and_version_bound(data, tmp_path):
    path = tmp_path / 'art.png'
    Image.new('RGB', (80, 100), '#f5f1e9').save(path)
    result = attach(data, path, '这是一张报告主线与证据关系的概览图片，用于分享。')
    assert result.report == data.report
    assert data.overview is None
    restored = ExportInput.model_validate_json(result.model_dump_json())
    html = export_html(restored)
    assert restored.overview.data_url in html
    assert 'ReportOverview' in html
    assert '下载分享图片' in html
    assert '<script src=' not in html
    restored.theme = 'night'
    validate_overview(restored)
    restored.report.title += '修订版'
    with pytest.raises(ValueError, match='版本不匹配'):
        export_html(restored)
    response = TestClient(app).post('/api/preview', json=restored.model_dump())
    assert response.status_code == 422


@pytest.mark.parametrize('url', ['https://example.com/image.png', 'data:image/svg+xml;base64,PHN2Zz4=', 'data:image/png;base64,aW52YWxpZA=='])
def test_reject_executable_remote_or_corrupt_image(url):
    with pytest.raises(ValueError):
        OverviewImage(data_url=url, report_digest='a' * 64, alt='这是对报告全景图的完整文字描述，以便读者理解。')


def test_brief_is_driven_by_all_sections_and_preserves_qualifiers(data):
    brief = image_brief(data)
    for section in data.report.sections:
        assert section.title in brief
    assert '"sources": []' in brief  # Missing source data stays missing.
    assert '观察、估计、预测和建议' in brief
    assert '不得画缺少数量的转化漏斗' in brief


def test_large_image_import_does_not_raise_generation_limit(data, tmp_path):
    # An actual large PNG exercises the import route's distinct request limit.
    import random
    image = Image.frombytes('RGB', (900, 900), random.Random(1).randbytes(900 * 900 * 3))
    path = tmp_path / 'large.png'
    image.save(path)
    result = attach(data, path, '这是一张报告主线与证据关系的概览图片，用于分享。')
    client = TestClient(app)
    assert client.post('/api/export', json=result.model_dump()).status_code == 200
    assert client.post('/api/generate', content=' ' * 2_000_001).status_code == 413
    preview = client.post('/api/preview', json=result.model_dump()).json()['url']
    response = client.get(preview + '/overview.png')
    assert response.status_code == 200
    assert response.content == path.read_bytes()
    assert response.headers['content-type'] == 'image/png'
    assert response.headers['content-disposition'].startswith('attachment;')
    assert client.get('/preview/nonexistent/overview.png').status_code == 404
