"""Structural, geometric and evidence boundaries for model-designed scenes."""
import math
import re


def validate_story(story, sections, check, refs):
    objects = {o.id: o for o in story.objects}
    links = {link.id: link for link in story.links}
    if len(objects) != len(story.objects) or len(links) != len(story.links):
        raise ValueError('场景对象和关系编号必须唯一。')
    if sorted(b.section_index for b in story.beats) != list(range(len(sections))):
        raise ValueError('每个章节必须且只能对应一个叙事分镜。')
    for i, obj in enumerate(story.objects):
        refs(obj.source_ids)
        check(obj.fact, obj.quote, path=f'/story/objects/{i}', field='fact')
        groups = {part.group for part in obj.parts}
        assembly_ids = [part.id for part in obj.assemblies]
        if len(assembly_ids) != len(set(assembly_ids)) or not set(assembly_ids) <= groups:
            raise ValueError('部件组必须唯一，并且引用真实存在的绘图分组。')
        if story.edition == 'semantic':
            if not obj.rationale.strip() or len(obj.parts) < 8 or len(assembly_ids) < 2:
                raise ValueError('专属造型需要解释与材料的联系，至少8个绘图部件、2个可独立展开的语义组。')
            order = [part.group for index, part in enumerate(obj.parts) if index == 0 or part.group != obj.parts[index-1].group]
            if len(order) != len(set(order)):
                raise ValueError('同组部件须连续绘制，避免重新分组改变遮挡顺序。')
        for other in story.objects[:i]:
            if abs(obj.x-other.x) < 205 and abs(obj.y-other.y) < 190:
                raise ValueError('场景对象过近，会遮挡图形或标签；请重新分配位置。')
        for part in obj.parts:
            if part.kind == 'path':
                if not re.fullmatch(r'[MmLlHhVvCcSsQqTtAaZz0-9.,+\s-]+', part.path) or not re.match(r'\s*[Mm]', part.path):
                    raise ValueError('图形路径只能含SVG几何命令和数字，不接受代码、网址或标签。')
                values = re.findall(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', part.path)
                if any(not math.isfinite(float(v)) or abs(float(v)) > 320 for v in values):
                    raise ValueError('图形路径坐标超出绘图范围。')
            elif part.width <= 0 or part.height <= 0 or part.x+part.width > 160 or part.y+part.height > 160:
                raise ValueError('图形部件超出160×160的局部画布。')
    for i, link in enumerate(story.links):
        if link.origin not in objects or link.destination not in objects or link.origin == link.destination:
            raise ValueError('场景关系必须连接两个存在且不同的对象。')
        refs(link.source_ids)
        check(link.label, link.quote, path=f'/story/links/{i}', field='label')
    for i, beat in enumerate(story.beats):
        if not set(beat.focus) <= objects.keys() or not set(beat.links) <= links.keys():
            raise ValueError('叙事分镜引用了不存在的对象或关系。')
        if len(set(beat.focus)) != len(beat.focus) or len(set(beat.links)) != len(beat.links):
            raise ValueError('分镜对象与关系不能重复。')
        actions = set()
        for action in beat.actions:
            key = (action.object_id, action.group)
            if key in actions or action.object_id not in beat.focus:
                raise ValueError('动作只能作用于本章焦点对象，同一部件组不能重复动作。')
            actions.add(key)
            if action.group not in {a.id for a in objects[action.object_id].assemblies}:
                raise ValueError('动作引用的部件组不存在。')
            assembly = next(a for a in objects[action.object_id].assemblies if a.id == action.group)
            if action.effect == 'reveal' and not any((assembly.dx, assembly.dy, assembly.angle)):
                raise ValueError('结构展开动作需要非零位移或转角，固定部件可使用描边观察。')
        if story.edition == 'semantic' and not beat.actions:
            raise ValueError('每个分镜需要至少一个与本章解释有关的部件动作。')
        for key in beat.links:
            if not {links[key].origin, links[key].destination} <= set(beat.focus):
                raise ValueError('分镜的关系两端必须同时在焦点对象中。')
        refs(beat.source_ids)
        check(beat.title, beat.quote, path=f'/story/beats/{i}', field='title')
        check(beat.caption, beat.quote, path=f'/story/beats/{i}', field='caption')
