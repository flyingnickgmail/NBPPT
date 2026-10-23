"""Report request binding and deterministic delivery validation."""
import base64
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from tools.report_studio.models import ExportInput, GenerateInput
from tools.report_studio.app import export_html

PRICES = {'report': 60, 'report_share': 40}


class WorkerReportRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_id: str = Field(pattern=r'^(?:report|reportshare)_[a-f0-9]{10}$')
    spec: dict


def parse_input(spec):
    if spec.get('generation_contract') != 'research-report-v1' or spec.get('operation') not in {'generate', 'continue', 'overview'}:
        raise ValueError('Invalid report contract')
    model = GenerateInput if spec['operation'] == 'generate' else ExportInput
    data = model.model_validate(spec['input'])
    if not data.content.strip():
        raise ValueError('Report material is empty')
    if spec.get('input_sha256') != hashlib.sha256(data.model_dump_json().encode()).hexdigest():
        raise ValueError('Report input binding mismatch')
    if spec['operation'] == 'generate' and data.mode != 'ai':
        raise ValueError('Local formatting does not require a worker')
    return data


def inspect_report(job_id: str, task_type: str, spec: dict, root: Path) -> dict:
    from gateway.delivery import contained_file
    source = parse_input(spec)
    expected = 'report_share' if spec['operation'] == 'overview' else 'report'
    prefix = 'reportshare_' if expected == 'report_share' else 'report_'
    if task_type != expected or not job_id.startswith(prefix):
        raise ValueError('Report task binding mismatch')
    path = contained_file(root, 'report.json')
    if path.stat().st_size > 10_000_000:
        raise ValueError('Report delivery too large')
    data = ExportInput.model_validate_json(path.read_text())
    if data.content != source.content or data.theme != source.theme or data.mode != 'ai':
        raise ValueError('Report completion differs from admitted material')
    if spec['operation'] == 'generate' and source.title and data.report.title != source.title:
        raise ValueError('Report title differs from admitted request')
    if spec['operation'] == 'overview' and (data.report != source.report or not data.overview):
        raise ValueError('Share image changed the report or is missing')
    if spec['operation'] != 'overview' and data.overview is not None:
        raise ValueError('Report task cannot deliver an unrequested share image')
    html = contained_file(root, 'report.html')
    if html.read_text() != export_html(data):
        raise ValueError('Report HTML differs from validated report')
    files = [path, html]
    if data.overview:
        image = contained_file(root, 'overview.png')
        if image.read_bytes() != base64.b64decode(data.overview.data_url.split(',', 1)[1], validate=True):
            raise ValueError('Share download differs from validated image')
        files.append(image)
    return {'version': 1, 'job_id': job_id, 'task_type': task_type,
            'planned_slides': 0, 'file_status': 'PASSED', 'content_status': 'NOT_REVIEWED',
            'files': [{'path': p.relative_to(root).as_posix(), 'size': p.stat().st_size,
                       'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(files)]}
