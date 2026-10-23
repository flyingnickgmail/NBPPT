import asyncio
from pathlib import Path
from pydantic import BaseModel
import pytest
from tools.report_studio import generator


class Reply(BaseModel):
    approved: bool


def test_image_is_resolved_before_temporary_subprocess_cwd(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path('candidate.png').write_bytes(b'fixture')
    monkeypatch.setattr(generator.shutil,'which',lambda _: '/codex')
    captured={}
    class Proc:
        returncode=0
        async def communicate(self,prompt):return b'',b''
    async def spawn(*cmd,**kwargs):
        captured['image']=cmd[cmd.index('--image')+1]
        captured['cwd']=kwargs['cwd']
        Path(cmd[cmd.index('--output-last-message')+1]).write_text('{"approved":true}')
        return Proc()
    monkeypatch.setattr(generator.asyncio,'create_subprocess_exec',spawn)
    reply=asyncio.run(generator.invoke('check',Reply,10,images=[Path('candidate.png')]))
    assert reply.approved
    assert captured['image']==str(tmp_path/'candidate.png')
    assert captured['cwd']!=str(tmp_path)


def test_missing_image_fails_before_starting_review(tmp_path,monkeypatch):
    monkeypatch.setattr(generator.shutil,'which',lambda _: '/codex')
    with pytest.raises(ValueError,match='图片不存在'):
        asyncio.run(generator.invoke('check',Reply,10,images=[tmp_path/'missing.png']))
