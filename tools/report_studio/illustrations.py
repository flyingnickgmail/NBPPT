"""Curated local illustrations; never accept model-provided paths or URLs."""
import base64
from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "static" / "illustrations"
CATALOG = {
    "economy": ("economy.png", "制度与经济传导", "柱廊、玻璃与环形构件组成的经济政策概念插画"),
    "technology": ("technology.png", "计算与连接", "计算核心与模块网络的技术概念插画"),
    "ecology": ("ecology.png", "能源与生态", "风力、树木与阶梯地形组成的生态概念插画"),
}


def illustration_asset(key: str) -> dict | None:
    if key not in CATALOG:
        return None
    filename, label, alt = CATALOG[key]
    return {"src": "data:image/png;base64," + base64.b64encode((ASSETS / filename).read_bytes()).decode("ascii"),
            "label": label, "alt": alt, "credit": "AI生成的主题概念插画 · 非实景"}
