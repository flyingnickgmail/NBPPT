"""Read completed reports/media through a deployed origin; never generate or bill.

The API key is read only from NBPPT_ACCEPTANCE_API_KEY. Receipts contain hashes
and check outcomes, not keys, source material, model logs or downloaded content.
"""
import argparse
import base64
import hashlib
import io
import json
import os
import re
import time
import zipfile
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from PIL import Image


class AcceptanceError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise AcceptanceError(message)


def check_deployment(base_url, api_key, report_id=None, media_jobs=(), *, verify=True):
    origin = urlsplit(base_url)
    require(origin.scheme == 'https' and origin.hostname and not origin.username
            and not origin.password and not origin.query and not origin.fragment
            and origin.path in ('', '/'), 'Use an HTTPS origin without credentials or query parameters')
    require(report_id or media_jobs, 'Choose at least one completed report or media job')
    if report_id:
        require(re.fullmatch(r'[a-f0-9]{32}', report_id), 'Invalid report ID')
    for job in media_jobs:
        require(re.fullmatch(r'(ppt|video)_[a-f0-9]{10}', job), 'Invalid media job ID')
    checks = []
    with httpx.Client(base_url=base_url.rstrip('/'), headers={'Authorization': 'Bearer ' + api_key},
                      verify=verify, timeout=90, follow_redirects=False, trust_env=False) as client:
        last_request = 0.0

        def request(path, status=200, **kwargs):
            nonlocal last_request
            # The shipped proxy permits 5 requests/second. Acceptance must
            # respect that policy, rather than increase limits or hide 503s.
            time.sleep(max(0, .22 - (time.monotonic() - last_request)))
            last_request = time.monotonic()
            response = client.request('POST' if 'json' in kwargs or 'content' in kwargs else 'GET', path, **kwargs)
            require(response.status_code == status, f'{path}: expected HTTP {status}, received {response.status_code}')
            return response

        def public_denied(path):
            request(path, 401, headers={'Authorization': ''})

        before = request('/api/wallet').json()['user']
        balance = lambda user: (user['credits_available'], user['credits_frozen'])
        if report_id:
            state = request('/api/reports/jobs/' + report_id).json()
            require(state['state'] == 'completed' and state['credits_held'] == 0, 'Report is not completed and settled')
            data = request('/api/reports/jobs/' + report_id + '/result').json()
            require(data.get('overview'), 'Choose a completed report containing a share image')
            path = '/api/reports/preview/' + report_id
            page = request(path).text
            require('window.ReportStudioConfig={apiBase:' in page, 'Online report did not use the platform route')
            html = request('/api/reports/jobs/' + report_id + '/download')
            require('attachment;' in html.headers.get('content-disposition', ''), 'HTML download header missing')
            require('window.ReportStudioConfig={apiBase:' not in html.text, 'Offline export includes platform routing')
            match = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html.text, re.S)
            require(match is not None and json.loads(match[1]) == data, 'Downloaded HTML does not contain the saved report')
            png = request(path + '/overview.png')
            raw = base64.b64decode(data['overview']['data_url'].split(',', 1)[1], validate=True)
            require(png.content == raw and png.headers.get('content-type') == 'image/png', 'PNG download does not match saved image')
            require('attachment;' in png.headers.get('content-disposition', ''), 'PNG download header missing')
            with Image.open(io.BytesIO(raw)) as image:
                image.verify()
            # Reproduce the former post-generation failure through the reverse proxy.
            exported = request('/api/reports/export', json=data)
            require(exported.content == html.content, 'Export POST differs from the saved offline download')
            request('/api/reports/review', json=data)
            for denied in [path, path + '/overview.png', '/api/reports/jobs/' + report_id + '/download']:
                public_denied(denied)
            checks.append({'kind': 'report_share', 'report_id': report_id,
                           'post_body_bytes': len(json.dumps(data).encode()), 'png_bytes': len(raw),
                           'png_sha256': hashlib.sha256(raw).hexdigest(),
                           'html_bytes': len(html.content), 'html_sha256': hashlib.sha256(html.content).hexdigest()})
        for job in media_jobs:
            manifest = request('/api/jobs/' + job + '/artifacts').json()
            suffix = '.pptx' if job.startswith('ppt_') else '.mp4'
            entry = next((f for f in manifest['files'] if f['path'].endswith(suffix)), None)
            require(entry is not None, 'Media manifest lacks the requested artifact')
            name = entry['path']
            require(not name.startswith('/') and '..' not in name.split('/') and '\\' not in name, 'Unsafe artifact path')
            media_path = '/artifacts/' + job + '/' + quote(name, safe='/')
            file = request(media_path)
            require(len(file.content) == entry['size'] and hashlib.sha256(file.content).hexdigest() == entry['sha256'], 'Media download failed size/hash verification')
            if suffix == '.pptx':
                with zipfile.ZipFile(io.BytesIO(file.content)) as deck:
                    require(deck.testzip() is None and 'ppt/presentation.xml' in deck.namelist(), 'PPTX cannot be reopened')
            else:
                partial = request(media_path, 206, headers={'Range': 'bytes=0-1023'})
                require(partial.content == file.content[:1024] and partial.headers.get('content-range', '').startswith('bytes 0-1023/'), 'Video Range download failed')
            public_denied(media_path)
            checks.append({'kind': job.split('_')[0], 'job_id': job, 'bytes': len(file.content), 'sha256': entry['sha256']})
        # Both application and nginx limits remain bounded; media defaults stay 1 MB.
        request('/api/reports/export', 413, content=b'x' * 11_000_000)
        request('/api/jobs', 413, content=b'x' * 2_000_000)
        after = request('/api/wallet').json()['user']
        require(balance(before) == balance(after), 'Acceptance changed available/frozen credits')
    return {'status': 'passed', 'model_calls': 0, 'wallet_unchanged': True,
            'checks': checks, 'oversize_rejected': True, 'unauthenticated_downloads_rejected': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--report-id')
    parser.add_argument('--media-job', action='append', default=[])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    key = os.environ.get('NBPPT_ACCEPTANCE_API_KEY', '')
    if not key:
        parser.error('Set NBPPT_ACCEPTANCE_API_KEY in the environment')
    try:
        receipt = check_deployment(args.base_url, key, args.report_id, args.media_job)
    except (AcceptanceError, httpx.HTTPError, ValueError, KeyError) as exc:
        # HTTP exceptions can include request data; emit only safe class information.
        message = str(exc) if isinstance(exc, AcceptanceError) else type(exc).__name__
        raise SystemExit('Deployment acceptance failed: ' + message) from None
    with args.output.open('x') as file:
        json.dump(receipt, file, ensure_ascii=False, indent=2)
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
