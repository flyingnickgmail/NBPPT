"""Opt-in Microsoft Edge voice adapter; explicit provider, no fallback or retry."""
from __future__ import annotations

import asyncio
import importlib.util
from importlib.metadata import version
import os
import shutil
import subprocess
from types import SimpleNamespace

VOICES = {"microsoft_yunxi": "zh-CN-YunxiNeural", "microsoft_xiaoxiao": "zh-CN-XiaoxiaoNeural"}
MAX_AUDIO_BYTES = 8 * 1024 * 1024


def _trim_edge_padding(samples, sample_rate: int):
    """Remove provider silence only; keep 250 ms handles and all inner pauses."""
    import numpy as np
    active = np.flatnonzero(np.abs(samples) > .001)  # -60 dBFS
    if not len(active):
        return samples
    handle = round(sample_rate * .25)
    return samples[max(0, active[0] - handle):min(len(samples), active[-1] + 1 + handle)]


def preflight_microsoft() -> None:
    if os.getenv("NBPPT_MICROSOFT_EDGE_ENABLED", "false").lower() != "true":
        raise RuntimeError("微软在线配音尚未启用，不会回退到其他音色")
    if importlib.util.find_spec("edge_tts") is None:
        raise RuntimeError("微软配音依赖 edge-tts 未安装")
    if version("edge-tts") != "7.3.1":
        raise RuntimeError("微软配音依赖版本未验收，请安装 requirements-microsoft-voice.txt")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("微软配音缺少 FFmpeg")


class MicrosoftEngine:
    def __init__(self, voice: str):
        preflight_microsoft()
        if voice not in VOICES:
            raise ValueError("微软音色不受支持")
        self.voice = VOICES[voice]

    async def _request(self, text: str) -> bytes:
        import edge_tts
        data = bytearray()
        async with asyncio.timeout(90):
            async for chunk in edge_tts.Communicate(text, self.voice, rate="-6%",
                                                   connect_timeout=15, receive_timeout=30).stream():
                if chunk["type"] == "audio":
                    data.extend(chunk["data"])
                    if len(data) > MAX_AUDIO_BYTES:
                        raise RuntimeError("微软音频超过大小限制")
        return bytes(data)

    def generate(self, text: str, sid: int = 0, speed: float = 1.0):
        if speed != 1.0 or not isinstance(text, str) or not text.strip() or len(text) > 180:
            raise ValueError("微软旁白需使用正常语速及受控长度")
        try:
            audio = asyncio.run(self._request(text))
        except Exception as exc:
            # Exception category helps diagnosis without logging signed URLs or service bodies.
            raise RuntimeError(f"微软在线配音请求失败（{type(exc).__name__}）；未自动重试或降级，请检查运行时和网络后显式重试任务") from None
        if not audio:
            raise RuntimeError("微软在线配音返回空音频")
        decoded = subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-nostdin",
            "-protocol_whitelist", "pipe", "-i", "pipe:0", "-t", "61", "-ar", "24000",
            "-ac", "1", "-f", "s16le", "pipe:1"], input=audio, capture_output=True, timeout=60)
        if decoded.returncode or not decoded.stdout or len(decoded.stdout) % 2:
            raise RuntimeError("微软配音不是有效音频")
        import numpy as np
        samples = np.frombuffer(decoded.stdout, dtype="<i2").astype(np.float32)/32768
        if len(samples) >= 61*24000 or not np.isfinite(samples).all() or np.max(np.abs(samples)) < .001:
            raise RuntimeError("微软配音超长或静音，拒绝截断和交付")
        return SimpleNamespace(samples=_trim_edge_padding(samples, 24000), sample_rate=24000)
