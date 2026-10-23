"""Load the project-owned skill used by both agents and report generation.

Only supported recipes enter the report schema prompt. Research-only recipes
remain available to the skill without pretending the renderer supports them.
"""
import json
from pathlib import Path

SKILL_ROOT = Path(__file__).parent / 'skills' / 'business-visual-storytelling'


def skill_reference(name: str) -> str:
    if name not in {'chart-policy.md', 'cover-standard.md', 'question-policy.md'}:
        raise ValueError('Unknown editorial skill reference')
    return (SKILL_ROOT / 'references' / name).read_text(encoding='utf-8')


def chart_skill_prompt() -> str:
    catalog = json.loads((SKILL_ROOT / 'references' / 'catalog.json').read_text(encoding='utf-8'))
    supported = [r for r in catalog['recipes'] if r['engine']['kind'] is not None]
    lines = [skill_reference('question-policy.md'), skill_reference('chart-policy.md'), '\n当前网页支持的问法→图种（仍须满足数据前提）：']
    for r in supported:
        lines.append(f"- {r['question']} → {r['engine']['kind']}（{r['name']}）。需要：{r['requires']}。注意：{r['avoid']}")
    return '\n'.join(lines)
