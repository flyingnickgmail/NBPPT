import json

import pytest

from tools.report_studio.editorial_skill import SKILL_ROOT, chart_skill_prompt, skill_reference
from tools.report_studio.generator import strict_schema
from tools.report_studio.models import Section
from tools.report_studio.overview_generation import OverviewReaderDesign
from tools.report_studio.overview_style import publication_standard


def test_catalog_never_advertises_a_nonexistent_schema_kind():
    catalog = json.loads((SKILL_ROOT / 'references/catalog.json').read_text())
    schema = strict_schema(Section)
    kinds = set()
    for definition in schema['$defs'].values():
        field = definition.get('properties', {}).get('kind', {})
        kinds.update(field.get('enum', []))
        if 'const' in field:
            kinds.add(field['const'])
    entries = catalog['recipes']
    assert len({r['id'] for r in entries}) == len(entries)
    for recipe in entries:
        assert recipe['requires'] and recipe['avoid'] and recipe['fallback']
        if recipe['engine']['kind'] is not None:
            assert recipe['engine']['kind'] in kinds
    prompt = chart_skill_prompt()
    for recipe in entries:
        # Reserve recipes cannot silently become a supported output choice.
        mapping = f"{recipe['question']} →"
        assert (mapping in prompt) == (recipe['engine']['kind'] is not None)


def test_cover_has_one_canonical_reference_and_supports_structural_explanation():
    assert publication_standard() == skill_reference('question-policy.md') + '\n' + skill_reference('cover-standard.md')
    grammar = OverviewReaderDesign.model_json_schema()['properties']['visual_grammar']['enum']
    assert 'annotated_structure' in grammar


def test_skill_loader_cannot_load_arbitrary_local_material():
    with pytest.raises(ValueError):
        skill_reference('../../../../.env')
