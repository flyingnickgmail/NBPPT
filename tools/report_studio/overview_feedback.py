"""Bounded feedback from actual visual QA, never provider/runtime errors."""
import json
from pathlib import Path


def read_quality_feedback(folder: Path):
    """Bounded, private QA observations; no material or runtime error forwarding."""
    try:
        review = folder / 'review-1.json'
        if not review.exists():
            review = folder / 'review-0.json'
        plan = folder / 'plan.json'
        if review.is_symlink() or plan.is_symlink() or review.stat().st_size > 32000 or plan.stat().st_size > 100000:
            return None
        value, design = json.loads(review.read_text()), json.loads(plan.read_text())
        if value.get('approved') is not False or not isinstance(value.get('issues'), list):
            return None
        issues = [i[:600] for i in value['issues'][:6] if isinstance(i, str)]
        return {'title': str(design.get('title', ''))[:80], 'issues': issues} if issues else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None

