"""Presentation helpers for quality and series groups.

Existing QualityGroups documents have no group_type: they remain quality groups
until an administrator explicitly changes them. Episode labels are never guessed
from a file's position; files with identical names can be labelled by an admin.
"""

import re
import unicodedata
from collections import defaultdict

GROUP_TYPES = frozenset(("quality", "series"))
AUTO_GROUP_MIN = 3
AUTO_QUALITY_MAX = 30
AUTO_SERIES_MAX = 500

# Release details are not part of a title. Keep years and other numbers: they
# can distinguish different films (or be the whole name of a series, e.g. 24).
_RELEASE_WORDS = frozenset("""
144p 240p 360p 480p 540p 576p 720p 1080p 1440p 2160p 4320p 4k 8k uhd hd sd
hdr hdr10 hdr10plus dv sdr 10bit 8bit hevc x264 x265 h264 h265 avc xvid divx
bluray blueray blu ray brrip bdrip bdremux remux webdl webrip web dl hdtv dvdrip dvd
cam hdcam predvd ts tc hdrip dvdscr r5 hindi english eng tamil telugu kannada
malayalam bengali marathi punjabi dual multi audio org original esub esubs sub subs
subtitle subtitles dd dd5 dd51 ddp ac3 aac mp3 flac truehd atmos 2ch 5ch 6ch
imax extended proper repack unrated theatrical directors cut amzn nf netflix dsnp
hmax hotstar prime zee sony mkv mp4 avi mov webm m4v wmv flv mpeg mpg m2ts vob
3gp iso www http https com net org
""".split())
_RESOLUTION = re.compile(r"(?<![A-Za-z0-9])(?:\d{3,4}[x×]\d{3,4}|(?:240|360|480|540|576|720|1080|1440|2160|4320)\s*p|[48]k)(?![A-Za-z0-9])", re.I)


def duration_seconds(value):
    """Read a positive runtime from a file document, a card, or a clock string."""
    if isinstance(value, dict):
        raw = value.get("duration_seconds")
        if raw in (None, "", 0, "0"):
            raw = value.get("duration")
    else:
        raw = value
    if isinstance(raw, bool):
        return 0
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError, OverflowError):
        pass
    text = str(raw or "").strip().replace("：", ":")
    parts = text.split(":")
    if len(parts) not in (2, 3) or not all(p.strip().isdigit() for p in parts):
        return 0
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def _normalized_title(text):
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    # Bracketed uploader/release tags vary between quality versions. Keep a
    # purely numeric tag because it may be a year or a numeric title.
    text = re.sub(r"\[([^\[\]]*)\]|\(([^()]*)\)",
                  lambda match: " " + (match.group(1) or match.group(2) or "").strip() + " "
                  if (match.group(1) or match.group(2) or "").strip().isdigit() else " ", text)
    text = _RESOLUTION.sub(" ", text)
    # Combining marks are part of words in Hindi and many other scripts; a
    # plain regex \w would split कहानी into fragments and conflate titles.
    chars = [ch if ch.isalnum() or unicodedata.category(ch).startswith("M") else " " for ch in text]
    words = [word for word in "".join(chars).split() if word not in _RELEASE_WORDS]
    return " ".join(words[:12])


def group_type(group):
    value = (group or {}).get("group_type")
    return value if isinstance(value, str) and value in GROUP_TYPES else "quality"


_EPISODE_PATTERNS = (
    (re.compile(r"(?<![A-Za-z0-9])s(?:eason\s*)?(\d{1,2})[\s._-]*e(?:p(?:isode)?)?[\s._-]*(\d{1,3})(?![A-Za-z0-9])", re.I), True),
    (re.compile(r"(?<![A-Za-z0-9])(\d{1,2})x(\d{2,3})(?![A-Za-z0-9])", re.I), True),
    (re.compile(r"(?<![A-Za-z0-9])(?:episode|ep|e|part|pt|chapter|ch)[\s._-]*(\d{1,3})(?![A-Za-z0-9])", re.I), False),
    (re.compile(r"(?<![A-Za-z0-9])(\d{1,3})\s*(?:of|/)\s*\d{1,3}(?![A-Za-z0-9])", re.I), False),
)


def _episode_match(name):
    text = str(name or "")
    matches = [(match.start(), index, match, has_season)
               for index, (pattern, has_season) in enumerate(_EPISODE_PATTERNS)
               if (match := pattern.search(text))]
    if not matches:
        return None
    _, _, match, has_season = min(matches, key=lambda item: (item[0], item[1]))
    return match, has_season


def episode_number(name):
    """Return (season, episode, label) only for an explicit filename marker."""
    found = _episode_match(name)
    if not found:
        return None
    match, has_season = found
    if has_season:
        season, episode = int(match.group(1)), int(match.group(2))
        return season, episode, f"S{season:02d}E{episode:02d}"
    episode = int(match.group(1))
    return None, episode, f"E{episode:02d}"


def episode_identity(name):
    detected = episode_number(name)
    return detected[2] if detected else ""


def quality_title_key(name):
    """Title independent of release tags; episode identity is compared separately."""
    text = str(name or "")
    for pattern, _ in _EPISODE_PATTERNS:
        text = pattern.sub(" ", text)
    return _normalized_title(text)


def _series_title_part(name):
    text = str(name or "")
    found = _episode_match(text)
    if not found:
        return ""
    match, _ = found
    prefix = text[:match.start()]
    # The marker itself may be inside a trailing [tag] or (tag).
    for opening, closing in (("[", "]"), ("(", ")")):
        if prefix.rfind(opening) > prefix.rfind(closing):
            prefix = prefix[:prefix.rfind(opening)]
    if _normalized_title(prefix):
        return prefix
    # Some uploads start with the episode marker instead of the show name.
    return text[match.end():]


def series_key(name):
    """Use the complete show title before its episode marker, not a short prefix."""
    return _normalized_title(_series_title_part(name))


def series_title(name):
    text = _RESOLUTION.sub(" ", _series_title_part(name))
    text = re.sub(r"\.(?:mkv|mp4|avi|mov|webm|m4v|wmv|flv|mpeg|mpg)$", "", text, flags=re.I)
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" \t|–-")
    return re.sub(r"^[\]\)}\s]+", "", text)


def auto_group_plan(rows, blocked=()):
    """Partition unowned files into safe series first, then quality groups.

    File IDs, not database copies, determine the threshold. A series needs at
    least two different explicit episodes; its members may have any runtimes.
    Quality variants need one title, episode identity and positive exact runtime.
    """
    blocked = set(blocked or ())
    unique = {}
    for row in rows:
        fid = row.get("file_id") or row.get("_id")
        if not fid:
            continue
        if row.get("group_auto_excluded"):
            blocked.add(fid)
        unique.setdefault(fid, row)
    available = {fid: row for fid, row in unique.items() if fid not in blocked}
    by_series = defaultdict(list)
    for fid, row in available.items():
        name = row.get("name") or row.get("file_name") or ""
        key = series_key(name) if episode_identity(name) else ""
        if len(key) >= 2:
            by_series[key].append((fid, row))

    plans, in_series = [], set()
    for key, entries in by_series.items():
        identities = {episode_identity(row.get("name") or row.get("file_name")) for _, row in entries}
        if AUTO_GROUP_MIN <= len(entries) <= AUTO_SERIES_MAX and len(identities) >= 2:
            plans.append({"kind": "series", "key": key, "items": entries})
            in_series.update(fid for fid, _ in entries)

    by_quality = defaultdict(list)
    for fid, row in available.items():
        if fid in in_series:
            continue
        name = row.get("name") or row.get("file_name") or ""
        title, seconds = quality_title_key(name), duration_seconds(row)
        if title and seconds:
            by_quality[(title, seconds, episode_identity(name))].append((fid, row))
    for (key, seconds, episode), entries in by_quality.items():
        if AUTO_GROUP_MIN <= len(entries) <= AUTO_QUALITY_MAX:
            plans.append({"kind": "quality", "key": key, "seconds": seconds,
                          "episode": episode, "items": entries})
    return plans


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
