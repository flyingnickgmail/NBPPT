"""Generate, render and inspect reports through the same pipeline as the local UI."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from fastapi import HTTPException

from .app import export_html, local_report
from .generator import ai_report, refine_report, design_story, design_spatial, design_editorial, design_reading
from .models import ExportInput, GenerateInput
from .quality import review_report
from .chart_design import recommend_design


def write_artifacts(data: ExportInput, folder: Path) -> dict:
    html = export_html(data)
    review = review_report(data.report, data.content)
    folder.mkdir(parents=True, exist_ok=False)
    (folder / 'report.json').write_text(data.model_dump_json(indent=2), encoding='utf-8')
    (folder / 'report.html').write_text(html, encoding='utf-8')
    (folder / 'quality.json').write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'design.json').write_text(json.dumps(recommend_design(data.report), ensure_ascii=False, indent=2), encoding='utf-8')
    return {'output': str(folder.resolve()), 'quality': review['status'], 'findings': review['findings']}


async def run(args) -> int:
    if args.command == 'generate':
        request = GenerateInput(content=args.input.read_text(encoding='utf-8'), title=args.title, mode=args.mode)
        if args.output.exists():
            raise ValueError('输出目录已存在；请使用新目录，保留已有报告。')
        report = await ai_report(request.content, request.title) if args.mode == 'ai' else local_report(request.content, request.title)
        result = write_artifacts(ExportInput(report=report, content=request.content, mode=args.mode), args.output)
    else:
        data = ExportInput.model_validate_json(args.input.read_text(encoding='utf-8'))
        if args.command in {'render', 'refine', 'compose', 'animate', 'design', 'reframe'}:
            if args.output.exists():
                raise ValueError('输出目录已存在；请使用新目录，保留已有报告。')
            if args.command != 'render':
                # A newly authored report must never retain a stale share image.
                data.overview = None
            if args.command == 'refine':
                data.report = await refine_report(data.report, data.content)
            if args.command == 'reframe':
                from .business_question import reframe_report
                data.report = await reframe_report(data.report, data.content, args.feedback)
            if args.command in {'refine', 'compose'}:
                data.report = await design_reading(data.report, data.content)
                if data.report.editorial or not (data.report.spatial or data.report.story):
                    data.report = await design_editorial(data.report, data.content)
                elif data.report.spatial:
                    data.report = await design_spatial(data.report, data.content)
                elif data.report.story:
                    data.report = await design_story(data.report, data.content)
            if args.command == 'animate':
                data.report = await design_story(data.report, data.content)
            if args.command == 'design':
                designer = design_spatial if args.style == 'spatial' else design_editorial
                data.report = await designer(data.report, data.content, feedback=args.feedback)
            result = write_artifacts(data, args.output)
        else:
            result = review_report(data.report, data.content)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 3 if args.strict and result['findings'] else 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description='灵动报告能力：生成、渲染、检查；不覆盖已有报告。')
    commands = parser.add_subparsers(dest='command', required=True)
    generate = commands.add_parser('generate', help='从材料生成报告，长材料自动内容复审')
    generate.add_argument('input', type=Path)
    generate.add_argument('--output', type=Path, required=True)
    generate.add_argument('--title', default='')
    generate.add_argument('--mode', choices=['ai', 'local'], default='ai')
    render = commands.add_parser('render', help='将结构化报告重新渲染，不调用模型')
    render.add_argument('input', type=Path)
    render.add_argument('--output', type=Path, required=True)
    refine = commands.add_parser('refine', help='复用已有初稿，只做内容复审与补图')
    refine.add_argument('input', type=Path)
    refine.add_argument('--output', type=Path, required=True)
    reframe = commands.add_parser('reframe', help='先审业务问题，再锁定数值与引文修订叙事')
    reframe.add_argument('input', type=Path)
    reframe.add_argument('--output', type=Path, required=True)
    reframe.add_argument('--feedback', required=True)
    compose = commands.add_parser('compose', help='从已复审内容继续模型读图编排与封面设计，不改事实')
    compose.add_argument('input', type=Path)
    compose.add_argument('--output', type=Path, required=True)
    animate = commands.add_parser('animate', help='依据材料与已有正文设计专属动态场景，不改正文')
    animate.add_argument('input', type=Path)
    animate.add_argument('--output', type=Path, required=True)
    design = commands.add_parser('design', help='保留正文，按材料重建空间构图与通用设计')
    design.add_argument('input', type=Path)
    design.add_argument('--output', type=Path, required=True)
    design.add_argument('--feedback', default='', help='实际视觉审查反馈，用于有依据的局部改进')
    design.add_argument('--style', choices=['editorial', 'spatial'], default='editorial', help='默认依据证据关系构图；立体表达需显式选择')
    check = commands.add_parser('check', help='输出材料与表达检查结果，不调用模型')
    check.add_argument('input', type=Path)
    check.add_argument('--strict', action='store_true', help='存在表达待检查项时退出码为3')
    try:
        return asyncio.run(run(parser.parse_args()))
    except (ValueError, OSError, HTTPException) as exc:
        print(json.dumps({'error': exc.detail if isinstance(exc, HTTPException) else str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
