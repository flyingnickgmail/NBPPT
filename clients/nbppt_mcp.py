"""Local stdio adapter for desktop clients. Credentials stay out of tool results."""
import argparse
import os
import tempfile
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer


def validate_config(config):
    url = urlparse(config['url'])
    if url.scheme != 'https' and not (url.scheme == 'http' and url.hostname in ('127.0.0.1', 'localhost', '::1')):
        raise ValueError('MCP requires HTTPS, or HTTP on loopback only')
    if url.username or url.password or url.query or url.fragment or url.path != '/mcp':
        raise ValueError('Expected a credential-free /mcp endpoint')
    if len(config['api_key']) < 32:
        raise ValueError('A private API key is required')
    return config


@asynccontextmanager
async def remote_client(config):
    async with httpx2.AsyncClient(headers={'Authorization': 'Bearer ' + config['api_key']}, timeout=30) as http:
        async with Client(streamable_http_client(config['url'], http_client=http), mode='legacy') as client:
            yield client


async def call_remote(config, name, arguments):
    async with remote_client(config) as client:
        result = await client.call_tool(name, arguments)
        if result.is_error:
            # Do not expose transport headers/credentials through exceptions.
            raise ValueError('NBPPT rejected the request: ' + ' '.join(c.text for c in result.content if c.type == 'text'))
        return json.loads(next(c.text for c in result.content if c.type == 'text'))


async def download_artifacts(config, result):
    job_id = result['job_id']
    if not re.fullmatch(r'ppt_[0-9a-f]{10}', job_id):
        raise ValueError('Invalid job id')
    root = Path(config['download_dir']).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory = root / job_id
    if directory.is_symlink():
        raise ValueError('Unsafe download destination')
    directory.mkdir(exist_ok=True, mode=0o700)
    base = config['url'].removesuffix('/mcp')
    paths = []
    async with httpx.AsyncClient(headers={'Authorization': 'Bearer ' + config['api_key']}, timeout=120, trust_env=False) as http:
        for entry in result['files']:
            name = entry['path']
            if not (name in (f'{job_id}_deck.pptx', f'{job_id}_deck_interactive.html') or
                    re.fullmatch(r'assets/slide_preview_[1-9][0-9]*\.png', name)):
                raise ValueError('Unexpected artifact path')
            target = directory / name
            if target.is_symlink() or target.parent.is_symlink():
                raise ValueError('Unsafe download destination')
            response = await http.get(base + f'/artifacts/{job_id}/' + name)
            response.raise_for_status()
            data = response.content
            if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise ValueError('Downloaded artifact integrity failure')
            target.parent.mkdir(exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as staging:
                temp = Path(staging.name)
                try:
                    staging.write(data)
                    staging.flush()
                    os.fsync(staging.fileno())
                    os.replace(temp, target)
                finally:
                    temp.unlink(missing_ok=True)
            paths.append(str(target))
    return {'job_id': job_id, 'slide_count': result['slide_count'], 'file_status': 'PASSED',
            'content_status': 'NOT_REVIEWED', 'local_files': paths}


def build_adapter(config):
    validate_config(config)
    server = MCPServer('NBPPT-local', instructions='通过NBPPT生成PPT。提交任务后每30秒查询进度，完成后下载产物到本机。不得重复创建同一任务。')

    @server.tool()
    async def list_templates() -> dict:
        """列出品牌风格参考，各页可使用不同布局。"""
        return await call_remote(config, 'list_templates', {})

    @server.tool()
    async def create_presentation(source: str, request_id: str, template_id: str = 'auto', slide_count: int = 0) -> dict:
        """将完整原文提交生成PPT，立即返回编号。request_id至少8位，重试必须复用。0页为自动。"""
        return await call_remote(config, 'create_presentation', {'source': source, 'request_id': request_id, 'template_id': template_id, 'slide_count': slide_count})

    @server.tool()
    async def get_job_status(job_id: str) -> dict:
        """查看任务状态；RUNNING时30秒后再查，COMPLETED后获取产物。"""
        return await call_remote(config, 'get_job_status', {'job_id': job_id})

    @server.tool()
    async def get_job_artifacts(job_id: str) -> dict:
        """下载已完成的PPTX/HTML/PNG并核对摘要，返回本机文件路径。"""
        result = await call_remote(config, 'get_job_artifacts', {'job_id': job_id})
        return await download_artifacts(config, result)

    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    path = Path(args.config).expanduser()
    if path.stat().st_mode & 0o077:
        raise ValueError('Client config must be private (chmod 600)')
    build_adapter(json.loads(path.read_text())).run()
