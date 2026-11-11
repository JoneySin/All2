"""Presentation helpers for quality and series groups.

Existing QualityGroups documents have no group_type: they remain quality groups
until an administrator explicitly changes them. Episode labels are never guessed
from a file's position; files with identical names can be labelled by an admin.
"""

import re

GROUP_TYPES = frozenset(("quality", "series"))


def group_type(group):
    value = (group or {}).get("group_type")
    return value if isinstance(value, str) and value in GROUP_TYPES else "quality"


_EPISODE_PATTERNS = (
    re.compile(r"(?<![A-Za-z0-9])s(?:eason\s*)?(\d{1,2})[\s._-]*e(?:p(?:isode)?)?[\s._-]*(\d{1,3})(?!\d)", re.I),
    re.compile(r"(?<![A-Za-z0-9])(\d{1,2})x(\d{1,3})(?!\d)", re.I),
)
_EPISODE_ONLY = re.compile(r"(?<![A-Za-z0-9])(?:episode|ep|e)[\s._-]*(\d{1,3})(?!\d)", re.I)


def episode_number(name):
    """Return (season, episode, label) only for an explicit filename marker."""
    name = str(name or "")
    for pattern in _EPISODE_PATTERNS:
        match = pattern.search(name)
        if match:
            season, episode = int(match.group(1)), int(match.group(2))
            return season, episode, f"S{season:02d}E{episode:02d}"
    match = _EPISODE_ONLY.search(name)
    if match:
        episode = int(match.group(1))
        return None, episode, f"E{episode:02d}"
    return None


def order_series(variants, group):
    """Apply admin order/labels, else sort explicit episode numbers naturally.

    Unnumbered files keep their stored member order. New members not yet in an
    admin's order are appended, without silently assigning episode numbers.
    """
    group = group or {}
    saved_order = {fid: i for i, fid in enumerate(group.get("episode_order") or [])}
    member_order = {fid: i for i, fid in enumerate(group.get("members") or [])}
    labels = {item.get("id"): item.get("label", "") for item in (group.get("episode_labels") or [])
              if isinstance(item, dict) and item.get("id")}
    rows = []
    for index, variant in enumerate(variants):
        item = dict(variant)
        fid = item.get("file_id")
        detected = episode_number(item.get("name"))
        custom = str(labels.get(fid) or "").strip()
        item["episode_custom_label"] = custom
        item["episode_detected_label"] = detected[2] if detected else ""
        item["episode_label"] = custom or item["episode_detected_label"]
        position = member_order.get(fid, len(member_order) + index)
        if saved_order:
            key = (0, saved_order[fid]) if fid in saved_order else (1, position)
        elif detected:
            key = (0, detected[0] if detected[0] is not None else 0, detected[1], position)
        else:
            key = (1, position)
        rows.append((key, item))
    rows.sort(key=lambda row: row[0])
    ordered = [row[1] for row in rows]
    for position, item in enumerate(ordered, 1):
        item["episode_position"] = position
    return ordered
