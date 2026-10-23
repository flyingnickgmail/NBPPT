import asyncio
from pathlib import Path
import httpx
import pytest
from gateway import main,voice_input
from test_security_delivery import manager,KEY_A,KEY_B,balance


def test_voice_endpoint_authentication_and_unconfigured_runtime(manager,monkeypatch):
    monkeypatch.delenv('NBPPT_ASR_BIN',raising=False)
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='https://test') as client:
            assert (await client.post('/api/voice/transcribe',content=b'x')).status_code==401
            r=await client.post('/api/voice/transcribe',headers={'Authorization':'Bearer '+KEY_A},content=b'x')
            assert r.status_code==422 and '未配置' in r.json()['detail']
            assert balance(manager)==(2000,0)
    asyncio.run(go())


@pytest.mark.parametrize('bad',['empty','oversize','duration','read_scope'])
def test_audio_rejections_and_cleanup(tmp_path,monkeypatch,bad):
    monkeypatch.setattr(voice_input,'runtime',lambda:('/trusted/whisper','/trusted/model'))
    monkeypatch.setenv('NBPPT_ASR_WORK_DIR',str(tmp_path))
    async def run(*args,**kwargs): return b'{"format":{"duration":"999"}}'
    monkeypatch.setattr(voice_input,'_run',run)
    class Req:
        async def stream(self):
            yield b'' if bad=='empty' else (b'x'*(voice_input.MAX_BYTES+1) if bad=='oversize' else b'x')
    async def go():
        principal={'scope':'read' if bad=='read_scope' else 'generate','user_id':bad}
        with pytest.raises((ValueError,PermissionError)):
            await voice_input.transcribe(Req(),principal)
        assert list(tmp_path.iterdir())==[]
    asyncio.run(go())
