"""One framing implementation for visual review and final footage encoding."""
import math


def validate_crop(crop):
    if not isinstance(crop,dict) or set(crop)-{'mode'} != {'cx','cy','zoom','pan_cx'}:
        raise ValueError('素材缺少审核后的横竖屏取景')
    if crop.get('mode','crop') not in {'crop','contain'}:
        raise ValueError('未知实景画面布局')
    for k in ('cx','cy','zoom','pan_cx'):
        v=crop[k]
        if type(v) not in (int,float) or not math.isfinite(v) or not ((1<=v<=1.5) if k=='zoom' else (0<=v<=1)):
            raise ValueError('素材取景参数超出范围')


def frame_filter(sw, sh, width, height, crop, duration):
    validate_crop(crop)
    if crop.get('mode','crop') == 'contain':
        return (f'setpts=PTS-STARTPTS,split=2[background][foreground];'
                f'[background]scale={width}:{height}:force_original_aspect_ratio=increase,'
                f'crop={width}:{height},boxblur=20:2,eq=brightness=-0.18[back];'
                f'[foreground]scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2[front];'
                '[back][front]overlay=(W-w)/2:(H-h)/2,setsar=1')
    ch=int(min(sh,sw*height/width)/crop['zoom'])//2*2
    cw=int(ch*width/height)//2*2
    x=max(0,min(sw-cw,round(sw*crop['cx']-cw/2)))
    x2=max(0,min(sw-cw,round(sw*crop['pan_cx']-cw/2)))
    y=max(0,min(sh-ch,round(sh*crop['cy']-ch/2)))
    motion=f"'{x}+({x2-x})*(1-cos(PI*min(t/{duration},1)))/2'"
    return f'setpts=PTS-STARTPTS,crop={cw}:{ch}:{motion}:{y},scale={width}:{height}:flags=lanczos,setsar=1'
