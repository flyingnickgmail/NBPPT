"""Validate geometry and provenance separately; geometry does not measure statistics."""
def validate_spatial(scene, sections, check, refs):
    ids = [g.id for g in scene.groups]
    if len(set(ids)) != len(ids):
        raise ValueError('空间分组编号必须唯一。')
    if scene.opening and (len(scene.opening) != len(ids) or set(scene.opening) != set(ids)):
        raise ValueError('开场顺序必须恰好包含每个语义分组一次。')
    if sorted(b.section_index for b in scene.beats) != list(range(len(sections))):
        raise ValueError('空间叙事须覆盖每章且不重复。')
    for i, group in enumerate(scene.groups):
        refs(group.source_ids)
        check(group.fact, group.quote, path=f'/spatial/groups/{i}', field='fact')
        if not any(p.group == group.id for p in scene.parts):
            raise ValueError('每个空间主体必须包含可见结构。')
    for part in scene.parts:
        if part.group not in ids:
            raise ValueError('空间部件引用不存在的组。')
        if any(len(p) != 2 for p in part.profile):
            raise ValueError('轮廓每点必须为两个坐标。')
        if part.shape == 'loft':
            if len(part.stations) < 3 or any(len(s) != 4 for s in part.stations):
                raise ValueError('连续外壳需要至少三个[x,半宽,底高,顶高]截面。')
            if any(w <= 0 or bottom >= top for x, w, bottom, top in part.stations):
                raise ValueError('外壳截面须有正半宽且底高小于顶高。')
            if any(a[0] >= b[0] for a, b in zip(part.stations, part.stations[1:])):
                raise ValueError('外壳截面x坐标必须严格递增。')
        elif part.stations:
            raise ValueError('只有连续外壳使用stations。')
        if part.shape == 'lathe':
            if len(part.profile) < 3 or any(r < 0 for z, r in part.profile):
                raise ValueError('旋转曲面需要至少三个[高度,半径]节点，半径非负。')
            if any(a[0] >= b[0] for a, b in zip(part.profile, part.profile[1:])):
                raise ValueError('旋转曲面高度须严格递增。')
            if max(r for z, r in part.profile) <= 0:
                raise ValueError('旋转曲面不能退化成直线。')
        if part.shape == 'prism':
            if len(part.profile) < 3:
                raise ValueError('棱柱轮廓至少三个点。')
            # The mesh fan triangulation needs convex, consistently wound polygons.
            points = part.profile
            if len({tuple(p) for p in points}) != len(points):
                raise ValueError('棱柱轮廓不能重复顶点。')
            def cross(a, b, c):
                return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
            for j, a in enumerate(points):
                b = points[(j+1) % len(points)]
                for k in range(j+2, len(points)):
                    if (k+1) % len(points) == j:
                        continue
                    c, d = points[k], points[(k+1) % len(points)]
                    if cross(a,b,c)*cross(a,b,d) < 0 and cross(c,d,a)*cross(c,d,b) < 0:
                        raise ValueError('棱柱轮廓不能自交。')
            crosses = []
            for j, a in enumerate(points):
                b, c = points[(j+1) % len(points)], points[(j+2) % len(points)]
                crosses.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
            nonzero = [v for v in crosses if abs(v) > 1e-8]
            if not nonzero or (min(nonzero) < 0 < max(nonzero)):
                raise ValueError('棱柱使用非退化凸轮廓，不能自交或凹陷。')
    for i, beat in enumerate(scene.beats):
        if len(set(beat.focus)) != len(beat.focus) or not set(beat.focus) <= set(ids):
            raise ValueError('空间分镜必须聚焦存在且不重复的分组。')
        refs(beat.source_ids)
        check(beat.title, beat.quote, path=f'/spatial/beats/{i}', field='title')
        check(beat.caption, beat.quote, path=f'/spatial/beats/{i}', field='caption')
