"""Authenticated, bounded, offline dictation; user confirms text before creating a job."""
import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import time

MAX_BYTES=10*1024*1024
MAX_SECONDS=180
_slot=asyncio.Semaphore(1)
_last={}


def runtime():
    binary=os.environ.get('NBPPT_ASR_BIN','')
    model=os.environ.get('NBPPT_ASR_MODEL','')
    if (not binary or not Path(binary).is_absolute() or not os.access(binary,os.X_OK)
            or not model or not Path(model).is_absolute() or Path(model).is_symlink() or not Path(model).is_file()
            or not shutil.which('ffmpeg') or not shutil.which('ffprobe')):
        raise ValueError('服务器尚未配置离线语音转写；可先粘贴语音转出的文字')
    return binary,model


def capability():
    try:
        runtime()
        return {'available':True,'provider':'whisper.cpp','max_seconds':MAX_SECONDS,'max_bytes':MAX_BYTES}
    except ValueError:
        return {'available':False,'provider':None,'max_seconds':MAX_SECONDS,'max_bytes':MAX_BYTES}


async def _run(*args,timeout=60):
    proc=await asyncio.create_subprocess_exec(*args,stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,start_new_session=True)
    try:
        out,_=await asyncio.wait_for(proc.communicate(),timeout)
        if proc.returncode:
            raise ValueError('音频解码或转写失败，请检查录音后重试')
        return out
    finally:
        if proc.returncode is None:
            from worker.direct_generation import stop_process
            await stop_process(proc)


async def transcribe(request,principal):
    if principal.get('scope') not in {'admin','generate'}:
        raise PermissionError('当前密钥没有语音转写权限')
    binary,model=runtime()
    now=time.monotonic();uid=principal['user_id']
    if now-_last.get(uid,-1000)<20:
        raise ValueError('语音转写过于频繁，请稍后重试')
    try:
        await asyncio.wait_for(_slot.acquire(),1)
    except asyncio.TimeoutError:
        raise ValueError('语音转写繁忙，请稍后重试') from None
    try:
        # Recheck inside the lease so parallel requests cannot race admission.
        if time.monotonic()-_last.get(uid,-1000)<20:
            raise ValueError('语音转写过于频繁，请稍后重试')
        if len(_last)>=1024:
            _last.pop(min(_last,key=_last.get))
        _last[uid]=now
        base=Path(os.getenv('NBPPT_ASR_WORK_DIR','').strip() or str(Path(__file__).resolve().parents[1]/'workspace/voice-input'))
        base.mkdir(parents=True,exist_ok=True,mode=0o700)
        with tempfile.TemporaryDirectory(prefix='dictation-',dir=base) as folder:
            work=Path(folder);raw=work/'recording';size=0
            async with asyncio.timeout(30):
                with raw.open('wb') as f:
                    async for chunk in request.stream():
                        size+=len(chunk)
                        if size>MAX_BYTES:
                            raise ValueError('录音超过10MB限制')
                        f.write(chunk)
            if not size:
                raise ValueError('录音为空')
            import json,math
            probe=json.loads(await _run(shutil.which('ffprobe'),'-v','error','-protocol_whitelist','file,pipe','-format_whitelist','wav,mp3,flac,ogg,mov,matroska,webm,aac','-show_format','-of','json',str(raw)))
            seconds=float(probe.get('format',{}).get('duration',0))
            if not math.isfinite(seconds) or not 0<seconds<=MAX_SECONDS:
                raise ValueError('录音时长必须在3分钟以内')
            wav=work/'speech.wav'
            await _run(shutil.which('ffmpeg'),'-v','error','-nostdin','-protocol_whitelist','file,pipe',
                       '-format_whitelist','wav,mp3,flac,ogg,mov,matroska,webm,aac','-i',str(raw),'-ar','16000','-ac','1',str(wav))
            prefix=work/'transcript'
            await _run(binary,'-m',model,'-f',str(wav),'-l','zh','-t','2','-ng','-nt',
                       '-otxt','-of',str(prefix),timeout=300)
            text=prefix.with_suffix('.txt').read_text().strip()
            if not text or len(text)>100000:
                raise ValueError('未识别到有效文字，请重录或粘贴文字')
            return {'text':text,'duration_seconds':seconds,'provider':'whisper.cpp',
                    'requires_confirmation':True,'credits_charged':0}
    finally:
        _slot.release()
