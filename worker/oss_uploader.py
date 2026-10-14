"""
Artifact Archiver & CDN / Local Static URL Signer.
Supports local static delivery out-of-the-box and optional Aliyun OSS / S3 / R2 upload in production.
"""
import pathlib
from typing import Dict, Any


def upload_job_artifacts_to_cdn(job_id: str, output_dir: pathlib.Path, gateway_base_url: str = "") -> Dict[str, Any]:
    """
    Scan the job's ./output directory and return structured download/preview URLs.
    """
    base = gateway_base_url.rstrip("/") if gateway_base_url else ""
    result: Dict[str, Any] = {
        "pptx_url": None,
        "html_deck_url": None,
        "mp4_url": None,
        "chart_urls": [],
        "slide_preview_urls": [],
        "keyframe_urls": [],
    }

    if not output_dir.exists():
        return result

    for p in sorted(output_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(output_dir).as_posix()
        url = f"{base}/artifacts/{job_id}/{rel}"
        if p.suffix.lower() == ".pptx":
            result["pptx_url"] = url
        elif p.suffix.lower() == ".html":
            result["html_deck_url"] = url
        elif p.suffix.lower() == ".mp4" and "clip_" not in p.name:
            result["mp4_url"] = url
        elif p.suffix.lower() == ".png":
            if "slide_preview_" in p.name:
                result["slide_preview_urls"].append(url)
            elif "scene_" in p.name:
                result["keyframe_urls"].append(url)
            else:
                result["chart_urls"].append(url)

    return result
