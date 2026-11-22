"""Small, local adaptations of the MIT YouTube Agent analysis utilities.

All scores here are editorial heuristics or descriptive analytics. They are not
estimates of virality or a causal explanation of video performance.
"""
from __future__ import annotations

import re
import statistics
import math
from typing import Any, Dict, Iterable, List, Optional

_FILLER = {"basically", "actually", "literally", "just", "really", "very", "welcome", "today", "subscribe", "channel"}
_VAGUE = {"amazing", "incredible", "insane", "crazy", "huge", "massive", "secret", "ultimate", "unbelievable", "revolutionary"}
_STOP = {"the", "a", "an", "of", "for", "to", "in", "on", "and", "or", "is", "are", "with", "your", "you", "my", "i", "this", "that", "it", "how", "what", "why"}


def hook_score(text: str) -> Dict[str, Any]:
    words = re.findall(r"[a-z0-9'%$.]+", text.lower())
    concrete = len(re.findall(r"\b(?:\d[\d,.]*\s?(?:%|k|m|x|s|m|h)?|\$\d)\b", text, re.I))
    named = sum(1 for w in text.split()[1:] if w[:1].isupper())
    specificity = max(0, min(100, 34 + concrete * 22 + min(18, named * 6) - 16 * sum(w in _VAGUE for w in words) - 5 * sum(w in _FILLER for w in words)))
    addressee = 26 + 20 * len(re.findall(r"\b(?:you|your|you're|yourself)\b", text, re.I))
    if re.search(r"\b(?:you|your|you're|yourself)\b", " ".join(words[:6]), re.I):
        addressee += 30
    stakes = 22 + 26 * len(re.findall(r"\b(?:lose|lost|wasting|waste|quit|fail|broke|cost|risk|before|stop|never|die|dead)\b", text, re.I)) + (14 if concrete else 0)
    curiosity = 24 + 17 * len(re.findall(r"\b(?:why|how|what|which|until|before|but|nobody|almost|except|reason|actually)\b", text, re.I))
    if text.strip().endswith("?"):
        curiosity += 18
    if re.search(r"\b(?:because|so that|which means)\b", text, re.I):
        curiosity -= 18
    n = len(words)
    brevity = 100 if 9 <= n <= 24 else max(10 if n > 24 else 30, 100 - (n - 24) * 7 if n > 24 else 100 - (9 - n) * 11)
    props = {"specificity": max(0, min(100, specificity)), "direct_address": max(0, min(100, addressee)),
             "stakes": max(0, min(100, stakes)), "curiosity": max(0, min(100, curiosity)), "brevity": max(0, min(100, brevity))}
    values = list(props.values())
    return {"properties": props, "heuristic_score": round(.6 * sum(values) / len(values) + .4 * min(values)),
            "band": "strong" if min(values) >= 72 else "workable" if sum(values) / len(values) >= 55 else "review",
            "note": "Editorial heuristic only; not a predictor of virality or views."}


def title_pair_check(title: str, thumbnail_text: str = "") -> Dict[str, Any]:
    title = str(title or "").strip()
    thumb = str(thumbnail_text or "").strip()
    words = lambda s: re.findall(r"[a-z0-9']+", s.lower())
    issues: List[str] = []
    if len(title) > 100: issues.append("Over 100 characters")
    if len(title) > 60: issues.append("May truncate in desktop search")
    if len(title) > 40: issues.append("Mobile feed may hide the subject")
    if len([w for w in title.split() if w.isupper() and len(w) > 2]) > 2: issues.append("Excessive all caps")
    if any(w in _VAGUE for w in words(title)): issues.append("Vague hype word")
    if not any(w not in _STOP for w in words(title)[:3]): issues.append("Subject is not front-loaded")
    shared = (set(words(title)) - _STOP) & (set(words(thumb)) - _STOP)
    if thumb and shared: issues.append("Thumbnail repeats title words: " + ", ".join(sorted(shared)))
    if len(words(thumb)) > 4: issues.append("Thumbnail text is longer than four words")
    return {"title": title, "title_chars": len(title), "thumbnail_words": len(words(thumb)), "issues": issues,
            "pass": not issues, "note": "Packaging lint only; it does not predict click-through rate."}


def retention_summary(points: Iterable[tuple[float, float]], duration_sec: Optional[float] = None) -> Dict[str, Any]:
    rows = []
    for x, y in points:
        try:
            xf, yf = float(x), float(y)
        except (TypeError, ValueError):
            continue
        if math.isfinite(xf) and math.isfinite(yf):
            rows.append((xf, yf))
    if len(rows) < 3:
        raise ValueError("At least three numeric retention points are required")
    rows.sort(key=lambda row: row[0])
    if duration_sec is not None and (not math.isfinite(float(duration_sec)) or float(duration_sec) <= 0):
        raise ValueError("duration_sec must be a positive finite number when supplied")
    pct_axis = max(x for x, _ in rows) <= 100.5
    x_to_sec = lambda x: x * duration_sec / 100 if pct_axis and duration_sec else x
    start = rows[0][1]
    cutoff = (30 / duration_sec * 100 if pct_axis and duration_sec else 10 if pct_axis else 30)
    hook_end = min((y for x, y in rows if x <= cutoff), default=start)
    cliffs = []
    slopes = []
    for (x0, y0), (x1, y1) in zip(rows, rows[1:]):
        span = max(x1 - x0, 1e-9)
        loss = y0 - y1
        slopes.append(loss / span)
        if loss > 0.8:
            cliffs.append({"from": x0, "to": x1, "lost_pct": loss, "at_seconds": x_to_sec(x1) if (not pct_axis or duration_sec) else None})
    cliffs.sort(key=lambda r: r["lost_pct"], reverse=True)
    return {"points": len(rows), "hook_leak_pct": round(start - hook_end, 2), "end_retention_pct": rows[-1][1],
            "largest_cliffs": cliffs[:5], "mean_loss_per_axis_unit": round(statistics.mean(slopes), 4),
            "note": "Descriptive channel analytics; cliffs identify where loss occurred, not why."}


def channel_outliers(videos: Iterable[Dict[str, Any]], minimum_per_channel: int = 4, min_multiple: float = 1.5) -> Dict[str, Any]:
    minimum_per_channel = max(2, int(minimum_per_channel))
    min_multiple = max(0.0, float(min_multiple))
    if not math.isfinite(min_multiple):
        raise ValueError("min_multiple must be finite")
    channels: Dict[str, List[Dict[str, Any]]] = {}
    for video in videos:
        channels.setdefault(str(video.get("channel") or "unknown"), []).append(video)
    outliers, skipped = [], []
    for channel, rows in channels.items():
        valid_rows = []
        for row in rows:
            try:
                count = float(row.get("views") or 0)
            except (TypeError, ValueError):
                continue
            if math.isfinite(count):
                valid_rows.append((row, max(0.0, count)))
        if len(valid_rows) < minimum_per_channel:
            skipped.append({"channel": channel, "video_count": len(rows)})
            continue
        views = [count for _, count in valid_rows]
        median = statistics.median(views)
        if median <= 0:
            skipped.append({"channel": channel, "video_count": len(rows), "reason": "zero median views"})
            continue
        for (row, _), count in zip(valid_rows, views):
            multiple = count / median
            if multiple >= min_multiple:
                outliers.append({"channel": channel, "title": str(row.get("title") or ""), "views": int(count),
                                 "channel_median": int(median), "multiple": round(multiple, 2), "url": str(row.get("url") or "")})
    outliers.sort(key=lambda row: row["multiple"], reverse=True)
    return {"outliers": outliers, "skipped_channels": skipped,
            "note": "Within-channel descriptive multiple only; title wording is not evidence of performance causality."}


def weekly_content_plan(ideas: Iterable[Dict[str, Any]], available_hours: float, already_in_progress: Optional[List[str]] = None) -> Dict[str, Any]:
    """Create a capacity-aware local editorial draft; never writes schedules."""
    ideas = list(ideas)
    underway = set(already_in_progress or [])
    try:
        budget = max(0.0, float(available_hours))
    except (TypeError, ValueError) as exc:
        raise ValueError("available_hours must be numeric") from exc
    if not math.isfinite(budget):
        raise ValueError("available_hours must be finite")
    slots = max(0, min(7, int(budget // 1.5)))
    candidates = [x for x in ideas if x.get("topic") and x.get("topic") not in underway]
    items = []
    if candidates and budget >= 3:
        items.append({"format": "anchor", "topic": candidates.pop(0).get("topic"), "hours_estimate": 3,
                      "basis": "Highest-priority supplied idea; estimated, not analytics-derived."})
        budget -= 3
    while candidates and len(items) < slots and budget >= 1.5:
        items.append({"format": "short", "topic": candidates.pop(0).get("topic"), "hours_estimate": 1.5,
                      "basis": "Supplied idea; capacity-based draft only."})
        budget -= 1.5
    return {"available_hours": float(available_hours), "planned_items": items,
            "unused_capacity_note": "No items or time were invented to fill a schedule.", "publishes_or_schedules": False}


def channel_audit(metrics: Dict[str, Any], targets: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Compare supplied metrics only against explicit channel targets; no defaults are invented."""
    if not metrics:
        return {"priority": None, "reason": "No channel analytics supplied; no performance conclusions can be made."}
    targets = targets or {}
    watch = metrics.get("average_view_percentage")
    ctr = metrics.get("impressions_ctr")
    if isinstance(watch, (float, int)) and math.isfinite(watch) and isinstance(targets.get("average_view_percentage"), (float, int)) and math.isfinite(targets["average_view_percentage"]) and watch < targets["average_view_percentage"]:
        priority, reason = "review_retention", "Supplied average view percentage is below the operator-provided target."
    elif isinstance(ctr, (float, int)) and math.isfinite(ctr) and isinstance(targets.get("impressions_ctr"), (float, int)) and math.isfinite(targets["impressions_ctr"]) and ctr < targets["impressions_ctr"]:
        priority, reason = "review_packaging", "Supplied impressions CTR is below the operator-provided target."
    else:
        priority, reason = "gather_more_data", "No supplied metric falls below an explicit target; inspect the source analytics before drawing conclusions."
    return {"priority": priority, "reason": reason, "source_metrics": dict(metrics), "targets": dict(targets),
            "note": "Descriptive comparison only; targets must be supplied by the channel owner."}
