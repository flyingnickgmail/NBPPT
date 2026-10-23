"""Trusted Chinese voice preparation, measured scene timing and audio mux."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import wave
import math


class SpeechError(RuntimeError):
    pass


MODEL_FILES = ("model.onnx", "lexicon.txt", "tokens.txt", "date.fst", "number.fst", "phone.fst")
KOKORO_FILES = ("model.onnx", "voices.bin", "tokens.txt", "lexicon-us-en.txt", "lexicon-zh.txt",
                "date-zh.fst", "number-zh.fst", "phone-zh.fst")
VOICE_IDS = {"melo": 0, "kokoro_female": 3, "kokoro_male": 58}


def trusted_model_dir(voice: str = "melo") -> Path:
    if voice not in VOICE_IDS:
        raise SpeechError("不支持的视频音色")
    value = os.environ.get("NBPPT_TTS_MODEL_DIR" if voice == "melo" else "NBPPT_KOKORO_MODEL_DIR", "")
    if not value or not Path(value).is_absolute():
        raise SpeechError("服务器未配置受信的中文语音模型目录")
    root = Path(value)
    if root.is_symlink() or not root.is_dir():
        raise SpeechError("中文语音模型目录无效")
    root = root.resolve()
    for name in MODEL_FILES if voice == "melo" else KOKORO_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise SpeechError(f"中文语音模型缺少受信文件：{name}")
    dictionary = root / ("dict" if voice == "melo" else "espeak-ng-data")
    if dictionary.is_symlink() or not dictionary.is_dir() or not dictionary.resolve().is_relative_to(root):
        raise SpeechError("中文语音模型缺少受信词典")
    return root


def build_kokoro_engine(model_dir: Path):
    import sherpa_onnx
    kokoro = sherpa_onnx.OfflineTtsKokoroModelConfig(
        model=str(model_dir / "model.onnx"), voices=str(model_dir / "voices.bin"),
        tokens=str(model_dir / "tokens.txt"), data_dir=str(model_dir / "espeak-ng-data"),
        lexicon=",".join(str(model_dir / name) for name in ("lexicon-us-en.txt", "lexicon-zh.txt")))
    return sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(kokoro=kokoro, num_threads=2, provider="cpu"),
        rule_fsts=",".join(str(model_dir / name) for name in ("date-zh.fst", "number-zh.fst", "phone-zh.fst"))))


def build_engine(model_dir: Path):
    try:
        import sherpa_onnx
    except ImportError as exc:
        raise SpeechError("独立中文语音运行时未安装 sherpa-onnx") from exc
    vits = sherpa_onnx.OfflineTtsVitsModelConfig(
        model=str(model_dir / "model.onnx"), lexicon=str(model_dir / "lexicon.txt"),
        tokens=str(model_dir / "tokens.txt"), dict_dir=str(model_dir / "dict"))
    model = sherpa_onnx.OfflineTtsModelConfig(vits=vits, num_threads=2, provider="cpu")
    config = sherpa_onnx.OfflineTtsConfig(
        model=model,
        rule_fsts=",".join(str(model_dir / name) for name in ("date.fst", "number.fst", "phone.fst")))
    engine = sherpa_onnx.OfflineTts(config)
    if engine.sample_rate <= 0:
        raise SpeechError("中文语音模型没有有效采样率")
    return engine


def _stamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _generate(engine, text: str, speed: float, sid: int = 0):
    import numpy as np
    generated = engine.generate(text, sid=sid, speed=speed)
    samples = np.asarray(generated.samples, dtype=np.float32)
    sample_rate = int(generated.sample_rate)
    if samples.ndim != 1 or len(samples) == 0 or sample_rate <= 0 or not np.isfinite(samples).all():
        raise SpeechError("中文语音模型返回了无效波形")
    return samples, sample_rate


def _write_pcm_wav(path: Path, samples, sample_rate: int) -> None:
    import numpy as np
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())


def allocate_scene_seconds(original, spoken, total, minimums):
    required=[max(3,math.ceil(seconds+.4),minimum) for seconds,minimum in zip(spoken,minimums)]
    if sum(required)>total:
        raise SpeechError('自然口播总长超过所选时长，请缩短文字或选择更长的视频；未加速或截断')
    assigned=[max(need,wanted) for need,wanted in zip(required,original)]
    while sum(assigned)>total:
        index=max(range(len(assigned)),key=lambda i:assigned[i]-required[i])
        assigned[index]-=1
    while sum(assigned)<total:
        index=min(range(len(assigned)),key=lambda i:assigned[i]-spoken[i])
        assigned[index]+=1
    return assigned


def prepare_manuscript_audio(job_dir, spec, manuscript, engine=None):
    """Generate once, allocate natural speech time, then hand the timed script to Claude."""
    from gateway.video_manuscript import validate_manuscript
    from gateway.video_contract import narration_density
    voice=spec.get('video_voice')
    if voice not in {'microsoft_yunxi','microsoft_xiaoxiao'}:
        raise SpeechError('前置自然配音仅支持已验收的微软音色')
    if engine is None:
        from worker.video_microsoft_voice import MicrosoftEngine
        engine=MicrosoftEngine(voice)
    work=Path(job_dir)/'prepared-speech'
    work.mkdir(exist_ok=False)
    spoken=[];records=[]
    for section in manuscript['sections']:
        samples,rate=_generate(engine,section['narration'],1.0)
        _write_pcm_wav(work/f"{section['scene_num']:02}.wav",samples,rate)
        seconds=len(samples)/rate;spoken.append(seconds)
        records.append({'scene_num':section['scene_num'],'narration':section['narration'],
                        'sample_rate':rate,'speech_duration_sec':seconds})
    times=allocate_scene_seconds([s['duration_sec'] for s in manuscript['sections']],spoken,
                                spec['video_duration_sec'],
                                [math.ceil(len(s['narration'])/narration_density(spec)[1]) for s in manuscript['sections']])
    timed={**manuscript,'sections':[{**s,'duration_sec':t} for s,t in zip(manuscript['sections'],times)]}
    timed=validate_manuscript(timed,spec)
    (Path(job_dir)/'manuscript.json').write_text(json.dumps(timed,ensure_ascii=False,indent=2))
    (Path(job_dir)/'speech_cache.json').write_text(json.dumps({'voice':voice,'scenes':records},ensure_ascii=False,indent=2))
    return timed


def _mux_audio(video: Path, audio: Path, destination: Path, duration: int, normalise: bool = False) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SpeechError("FFmpeg 未安装，无法封装中文配音")
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
               "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-ac", "1",
               "-t", str(duration), "-movflags", "+faststart"]
    if normalise:
        if __package__ in (None, ""):
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from gateway.audio_contract import measure_loudness
        levels=measure_loudness(audio)
        # Leave a decibel of headroom for AAC and the subsequent subtitle mux.
        filters=("loudnorm=I=-16:TP=-2.5:LRA=7:linear=true:"
                 f"measured_I={levels['input_i']}:measured_TP={levels['input_tp']}:"
                 f"measured_LRA={levels['input_lra']}:measured_thresh={levels['input_thresh']}:"
                 f"offset={levels['target_offset']}")
        command += ["-af", filters]
    command += [str(destination)]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               start_new_session=False)
    try:
        _, stderr = process.communicate(timeout=max(60, duration * 5))
    except subprocess.TimeoutExpired as exc:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        raise SpeechError("中文配音封装超时") from exc
    if process.returncode != 0:
        raise SpeechError("中文配音封装失败：" + stderr.decode("utf-8", errors="replace")[-800:])


def synthesize_narration(job_dir: Path, job_id: str, plan: dict, engine=None) -> dict:
    import numpy as np
    raw_job_dir = Path(job_dir)
    if raw_job_dir.is_symlink():
        raise SpeechError("配音目录与任务编号不匹配")
    job_dir = raw_job_dir.resolve()
    if not re.fullmatch(r"video_[a-f0-9]{10}", job_id) or job_dir.name != job_id:
        raise SpeechError("配音目录与任务编号不匹配")
    staging = job_dir / "staging"
    video = staging / f"{job_id}_video.mp4"
    if (staging.is_symlink() or not staging.is_dir() or not staging.resolve().is_relative_to(job_dir)
            or video.is_symlink() or not video.is_file() or not video.resolve().is_relative_to(staging.resolve())):
        raise SpeechError("缺少安全的待配音视频")
    scenes = plan.get("video_scenes")
    if not isinstance(scenes, list) or not scenes:
        raise SpeechError("缺少已验证的配音场景")
    voice = plan.get("video_voice", "melo")
    microsoft = voice in {"microsoft_yunxi", "microsoft_xiaoxiao"}
    if voice not in VOICE_IDS and not microsoft:
        raise SpeechError("不支持的视频音色")
    cache_path=job_dir/'speech_cache.json'
    cached=None
    if microsoft and cache_path.is_file():
        if cache_path.is_symlink():
            raise SpeechError('配音缓存路径不安全')
        cached=json.loads(cache_path.read_text())
        if cached.get('voice')!=voice or len(cached.get('scenes',[]))!=len(scenes):
            raise SpeechError('配音缓存与分镜不一致')
    if engine is None and cached is None:
        if microsoft:
            if __package__ in (None, ""):
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from worker.video_microsoft_voice import MicrosoftEngine
            engine = MicrosoftEngine(voice)
        else:
            model_dir = trusted_model_dir(voice)
            engine = build_engine(model_dir) if voice == "melo" else build_kokoro_engine(model_dir)
    work = staging / ".speech-work"
    work.mkdir(parents=True, exist_ok=False)
    scene_results = []
    full_audio = []
    sample_rate = None
    cursor_samples = 0
    vtt = ["WEBVTT", ""]
    try:
        for index, scene in enumerate(scenes, 1):
            narration = scene["narration"]
            scene_duration = int(scene["duration_sec"])
            breathing = min(.4, max(.25, scene_duration * .08))
            max_speech = scene_duration - breathing
            if cached:
                record=cached['scenes'][index-1]
                path=job_dir/'prepared-speech'/f'{index:02}.wav'
                if (record.get('narration')!=narration or record.get('scene_num')!=index or path.is_symlink()
                        or not path.resolve().is_relative_to(job_dir)):
                    raise SpeechError('缓存口播与已审核文字不一致')
                with wave.open(str(path)) as audio:
                    if audio.getnchannels()!=1 or audio.getsampwidth()!=2:
                        raise SpeechError('缓存音频格式不正确')
                    current_rate=audio.getframerate()
                    samples=np.frombuffer(audio.readframes(audio.getnframes()),dtype='<i2').astype(np.float32)/32768
                if not len(samples) or current_rate!=record.get('sample_rate'):
                    raise SpeechError('缓存音频为空或采样率改变')
            else:
                samples, current_rate = _generate(engine, narration, 1.0, VOICE_IDS.get(voice, 0))
            if sample_rate is None:
                sample_rate = current_rate
            elif current_rate != sample_rate:
                raise SpeechError("中文语音模型在场景间改变了采样率")
            speech_duration = len(samples) / sample_rate
            speed = 1.0
            if speech_duration > max_speech:
                if microsoft:
                    raise SpeechError(f"第 {index} 场自然配音超出镜头，请缩短旁白；未加速、截断或自动付费重试")
                speed = min(1.2, max(1.01, speech_duration / max_speech * 1.02))
                samples, current_rate = _generate(engine, narration, speed, VOICE_IDS[voice])
                if current_rate != sample_rate:
                    raise SpeechError("中文语音模型在重试时改变了采样率")
                speech_duration = len(samples) / sample_rate
            if speech_duration > max_speech + 1 / sample_rate:
                raise SpeechError(f"第 {index} 场配音在 1.2 倍速内仍放不下，拒绝截断")
            scene_frames = scene_duration * sample_rate
            if len(samples) > scene_frames:
                raise SpeechError(f"第 {index} 场配音超过场景时长")
            full_audio.append(samples)
            full_audio.append(np.zeros(scene_frames - len(samples), dtype=np.float32))
            cue_start = cursor_samples / sample_rate
            # Keep the sentence visible until this shot ends, including its
            # breathing room. Speech duration remains separate audit evidence;
            # a short spoken phrase must not produce a flashing subtitle.
            cue_end = cue_start + scene_duration
            vtt.extend([f"{_stamp(cue_start)} --> {_stamp(cue_end)}", html.escape(narration), ""])
            cursor_samples += scene_frames
            scene_results.append({"scene_num": index, "speed": round(speed, 3),
                                  "speech_duration_sec": round(speech_duration, 3),
                                  "caption_duration_sec": scene_duration,
                                  "scene_duration_sec": scene_duration})
            print(json.dumps({"type": "progress", "scene": index, "total_scenes": len(scenes),
                              "pct": round(index * 80 / len(scenes), 1)}), flush=True)
        assert sample_rate is not None
        combined = np.concatenate(full_audio)
        wav_path = work / "narration.wav"
        if plan.get('video_visual_mode')=='live_action':
            from worker.video_music import mix_original_bed
            combined=mix_original_bed(combined,sample_rate)
        _write_pcm_wav(wav_path, combined, sample_rate)
        subtitles = staging / "subtitles.vtt"
        subtitles.write_text("\n".join(vtt), encoding="utf-8")
        muxed = work / "with-audio.mp4"
        total_duration = sum(int(scene["duration_sec"]) for scene in scenes)
        _mux_audio(video, wav_path, muxed, total_duration, normalise=microsoft or plan.get("generation_contract")=="story-video-v2")
        os.replace(muxed, video)
        result = {"provider": "microsoft_edge" if microsoft else ("melo_tts" if voice == "melo" else "kokoro"), "voice": voice, "sample_rate": sample_rate,
                  "total_duration_sec": total_duration, "scenes": scene_results}
        (job_dir / "speech_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"type": "progress", "pct": 100, "message": "audio_muxed"}), flush=True)
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    if __package__ in (None, ''):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--prepare",action='store_true')
    args = parser.parse_args()
    try:
        raw_job_dir = Path(args.job_dir)
        if raw_job_dir.is_symlink():
            raise SpeechError("配音目录与任务编号不匹配")
        job_dir = raw_job_dir.resolve()
        if args.prepare:
            if __package__ in (None, ''):
                sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
            if job_dir.name!=args.job_id or not re.fullmatch(r'video_[a-f0-9]{10}',args.job_id):
                raise SpeechError('配音准备任务编号不一致')
            spec=json.loads((job_dir/'voice_prepare_spec.json').read_text())
            manuscript=json.loads((job_dir/'manuscript.json').read_text())
            prepare_manuscript_audio(job_dir,spec,manuscript)
            return 0
        plan_path = job_dir / "validated_video_plan.json"
        if (plan_path.is_symlink() or not plan_path.is_file()
                or not plan_path.resolve().is_relative_to(job_dir) or plan_path.stat().st_size > 256 * 1024):
            raise SpeechError("缺少可信的视频配音计划")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        synthesize_narration(job_dir, args.job_id, plan)
        print(json.dumps({"type": "completed"}), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
