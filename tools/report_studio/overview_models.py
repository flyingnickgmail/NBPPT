"""Portable, version-bound overview artwork. No remote paths or executable SVG."""
import base64
import io

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator


class OverviewImage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    report_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    data_url: str = Field(max_length=8_000_000)
    alt: str = Field(min_length=20, max_length=1500)
    caption: str = Field(default='一图读懂 · AI辅助图解', max_length=120)

    @field_validator('data_url')
    @classmethod
    def validate_png(cls, value):
        prefix = 'data:image/png;base64,'
        if not value.startswith(prefix):
            raise ValueError('全景图仅接受内嵌 PNG 图片')
        try:
            raw = base64.b64decode(value[len(prefix):], validate=True)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format != 'PNG' or image.width * image.height > 25_000_000 or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('全景图须为不超过 2500 万像素的静态 PNG')
                image.verify()
        except Exception as exc:
            raise ValueError('全景图 PNG 数据无效') from exc
        return value
