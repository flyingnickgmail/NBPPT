"""Check the one current capability table against executable, data-only contracts."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
START = '<!-- video-contract:start -->'
END = '<!-- video-contract:end -->'
CANONICAL = ROOT / 'docs/VIDEO_CAPABILITIES.md'


def capability_table():
    from gateway.video_contract import validate_video_spec, VIDEO_VOICES
    from gateway.exec_pitch_contract import MAX_SECONDS, MAX_SHOTS, MAX_SECTIONS
    from gateway.audio_contract import profile_targets

    def maximum(preset, provider):
        spec = dict(generation_contract='story-video-v2' if provider == 'claude_cli' else 'skill-video-v1',
                    original_prompt_cn='先核对记录，再由负责人确认。', video_aspect_ratio='16:9',
                    video_preset=preset, planner_provider=provider)
        if preset == 'exec_pitch':
            spec.update(generation_contract='exec-pitch-v1', planner_provider='approved_data',
                        video_voice='approved_local', video_narration=True,
                        video_visual_mode='registered_local', video_input_id='a'*64, video_input_owner='b'*64)
        def valid(seconds):
            try:
                validate_video_spec({**spec, 'video_duration_sec': seconds})
                return True
            except (ValueError, RuntimeError):
                return False
        if not valid(6) or valid(3600):
            raise ValueError('视频契约需要重新核查，不能生成一个猜测的能力表')
        low, high = 6, 3600
        while high-low > 1:
            mid = (low+high)//2
            if valid(mid): low = mid
            else: high = mid
        return low

    limits = [maximum('short', 'codex_cli'), maximum('legacy', 'codex_cli'),
              maximum('legacy', 'claude_cli'), maximum('exec_pitch', 'approved_data')]
    if limits[-1] != MAX_SECONDS:
        raise ValueError('长片与通用视频契约的时长上限不一致')
    rows = ['| 预设 | 输入与规划方式 | 时长（秒） |', '|---|---|---|',
            f'| `short` | Codex／Claude 短片 | 6–{limits[0]} |',
            f'| `legacy` | Codex 原文规划 | 6–{limits[1]} |',
            f'| `legacy` | Claude 内容与口播、故事分镜 | 6–{limits[2]} |',
            f'| `exec_pitch` | 账户隔离的已登记口播与镜头，不重新请求模型 | 6–{limits[3]} |', '',
            f'长片上限：{MAX_SECTIONS} 个口播段、{MAX_SHOTS} 个镜头。', '',
            '契约支持的音色标识：'+', '.join(f'`{v}`' for v in sorted(VIDEO_VOICES))+'。', '',
            '| 混音配置 | 目标响度 | 最终真峰值上限 |', '|---|---|---|']
    for profile in ('legacy', 'exec_pitch_p3'):
        target = profile_targets(profile)
        rows.append(f"| `{profile}` | {target['integrated']} LUFS | {target['maximum_peak']} dBTP |")
    return '\n'.join(rows)


def check_document(text, expected):
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise ValueError('当前能力文档缺少唯一契约表边界')
    actual = text.split(START)[1].split(END)[0].strip()
    if actual != expected:
        raise ValueError('当前能力表与实际契约不一致；运行 tools/check_video_docs.py --write 后审阅差异')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='只更新能力表标记内内容；默认只读检查')
    args = parser.parse_args()
    expected = capability_table()
    text = CANONICAL.read_text()
    if args.write:
        if text.count(START) != 1 or text.count(END) != 1:
            raise ValueError('拒绝覆盖边界异常的文档')
        before, rest = text.split(START)
        _, after = rest.split(END)
        CANONICAL.write_text(before+START+'\n'+expected+'\n'+END+after)
    check_document(CANONICAL.read_text(), expected)
    for name in ('VIDEO_AUTHORING.md', 'VIDEO_PRODUCTION.md'):
        header = (ROOT/'docs'/name).read_text().splitlines()[:8]
        if not any('VIDEO_CAPABILITIES.md' in line for line in header):
            raise ValueError(f'{name} 必须在开头指向唯一当前能力说明')
    print('Video capability documents match current executable contracts.')


if __name__ == '__main__':
    main()
