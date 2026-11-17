"""Deterministic Script Quality & Editorial Gate for CurioLoop.

Enforces:
1. Calibrated duration: 42-58s target, 40-60s hard ceiling at measured 2.46 WPS.
2. Word count: 103-140 words target, 90-148 words hard boundaries.
3. Hook rules: <= 14 words, no banned openers, concrete details.
4. Banned phrases & weak CTAs check.
5. Pacing: max 22 words per sentence, target <= 14 words average.
6. Contextual editorial category check: Allows MYSTERY, HISTORY, SPACE.
   Strictly rejects biology, human anatomy, animal trivia, and generic science lists.
7. Research Dossier alignment: Key script claims substantiated in verified claims.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from curiosity_engine.content.editorial_policy import (
    AVG_SENTENCE_WORDS_TARGET,
    BANNED_OPENERS,
    BANNED_PHRASES,
    CALIBRATED_WORDS_PER_SECOND,
    HARD_MAX_DURATION_SEC,
    HARD_MIN_DURATION_SEC,
    HARD_WORD_MAX,
    HARD_WORD_MIN,
    MAX_HOOK_WORDS,
    MAX_SENTENCE_WORDS,
    PAUSE_PER_SENTENCE_SEC,
    TARGET_MAX_DURATION_SEC,
    TARGET_MIN_DURATION_SEC,
    TARGET_WORD_MAX,
    TARGET_WORD_MIN,
    WEAK_CTAS,
    is_forbidden_content,
    validate_editorial_category,
)

logger = logging.getLogger("curiosity_engine.script_validator")

STOP_WORDS: Set[str] = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for", "with", "from",
    "by", "is", "are", "was", "were", "be", "been", "it", "its", "this", "that", "he", "she",
    "they", "them", "his", "her", "their", "you", "your", "i", "we", "our", "as", "so", "if",
    "then", "than", "not", "no", "just", "into", "out", "up",
}


def extract_script_fields(data: Any) -> Tuple[str, str, str, List[str], str]:
    """Extract (title, category, hook, beats, full_text) from diverse script representations."""
    title = ""
    category = ""
    hook = ""
    beats: List[str] = []

    if isinstance(data, str):
        text = data
    elif isinstance(data, dict):
        title = str(data.get("title", "") or "")
        category = str(data.get("category", "") or data.get("niche", "") or "")
        hook = str(data.get("hook", "") or "")

        # Look in lines, beats, segments, scenes
        for key in ("lines", "beats", "segments", "scenes"):
            if isinstance(data.get(key), list) and data[key]:
                for item in data[key]:
                    if isinstance(item, str):
                        beats.append(item)
                    elif isinstance(item, dict):
                        for k in ("text", "narration", "line", "voiceover"):
                            if item.get(k):
                                beats.append(str(item[k]))
                                break
                break

        if beats:
            text = " ".join(beats)
        else:
            text = ""
            for key in ("script", "narration", "text"):
                if data.get(key):
                    text = str(data[key])
                    break
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                beats.append(item)
            elif isinstance(item, dict):
                for k in ("text", "narration", "line", "voiceover"):
                    if item.get(k):
                        beats.append(str(item[k]))
                        break
        text = " ".join(beats)
    else:
        raise ValueError("Unsupported input format for script extraction")

    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ValueError("No narration text found in script data")

    if not hook and beats:
        hook = beats[0]

    return title, category, hook, beats, text


def get_sentences(text: str) -> List[str]:
    """Split text into sentences on terminal punctuation."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def get_words(text: str) -> List[str]:
    """Extract spoken word tokens."""
    return re.findall(r"[A-Za-z0-9$%'’\-]+", text)


def get_content_words(text: str) -> Set[str]:
    """Extract meaningful content words for echo and similarity analysis."""
    return {w.lower() for w in get_words(text) if w.lower() not in STOP_WORDS and len(w) > 2}


def validate_script(
    data: Any,
    wps: float = CALIBRATED_WORDS_PER_SECOND,
    dossier: Optional[Any] = None,
) -> Dict[str, Any]:
    """Deterministically validate a script against viral shorts rules and CurioLoop editorial policy.

    Returns dict with keys:
      ok (bool): True if zero errors
      words (int): Spoken word count
      sentences (int): Number of sentences
      est_seconds (float): Estimated runtime at calibrated wps
      errors (List[str]): Hard blocking errors
      warnings (List[str]): Editorial quality warnings
    """
    errors: List[str] = []
    warnings: List[str] = []

    try:
        title, category, hook, beats, text = extract_script_fields(data)
    except Exception as e:
        return {
            "ok": False,
            "words": 0,
            "sentences": 0,
            "est_seconds": 0.0,
            "errors": [f"Input extraction failed: {e}"],
            "warnings": [],
        }

    sents = get_sentences(text)
    word_tokens = get_words(text)
    n_words = len(word_tokens)

    # 1. Calibrated Duration Check
    est_duration = (n_words / wps) + (PAUSE_PER_SENTENCE_SEC * len(sents))
    if est_duration < HARD_MIN_DURATION_SEC or est_duration > HARD_MAX_DURATION_SEC:
        errors.append(
            f"Estimated duration {est_duration:.1f}s outside hard range "
            f"{HARD_MIN_DURATION_SEC:.0f}-{HARD_MAX_DURATION_SEC:.0f}s ({n_words} words at {wps:.2f} WPS)."
        )
    elif est_duration < TARGET_MIN_DURATION_SEC or est_duration > TARGET_MAX_DURATION_SEC:
        warnings.append(
            f"Estimated duration {est_duration:.1f}s outside target "
            f"{TARGET_MIN_DURATION_SEC:.0f}-{TARGET_MAX_DURATION_SEC:.0f}s ({n_words} words)."
        )

    # 2. Word Count Bounds
    if n_words < HARD_WORD_MIN or n_words > HARD_WORD_MAX:
        errors.append(
            f"Word count {n_words} outside hard boundaries [{HARD_WORD_MIN}, {HARD_WORD_MAX}]."
        )
    elif n_words < TARGET_WORD_MIN or n_words > TARGET_WORD_MAX:
        warnings.append(
            f"Word count {n_words} outside optimal target [{TARGET_WORD_MIN}, {TARGET_WORD_MAX}]."
        )

    # 3. Hook Rules (<= 14 words, no banned openers)
    first_sent = hook.strip() or (sents[0] if sents else "")
    hook_words = get_words(first_sent)
    if len(hook_words) > MAX_HOOK_WORDS:
        errors.append(f"Hook exceeds {MAX_HOOK_WORDS} words ({len(hook_words)} words): '{first_sent[:70]}'")

    low_first = first_sent.lower()
    for opener in BANNED_OPENERS:
        if low_first.startswith(opener.lower()):
            errors.append(f"Hook starts with prohibited opener: '{opener}'")
            break

    if not (re.search(r"\d", first_sent) or re.search(r"\b[A-Z][a-z]+", first_sent[1:])):
        warnings.append("Hook lacks concrete numbers or proper nouns.")

    # 4. Slop & Weak CTAs
    low_text = text.lower()
    for phrase in BANNED_PHRASES:
        if re.search(r"\b" + re.escape(phrase.lower()), low_text):
            errors.append(f"Contains prohibited AI slop/sensational phrase: '{phrase}'")

    for cta in WEAK_CTAS:
        if cta.lower() in low_text:
            errors.append(f"Contains prohibited weak CTA: '{cta}'")

    # 5. Editorial Category Policy (Contextual Validation)
    is_valid_cat, detected_cat, cat_reason = validate_editorial_category(
        text=f"{title} {text}".strip(),
        declared_category=category,
    )
    if not is_valid_cat:
        errors.append(f"Editorial category policy violation: {cat_reason}")

    # Explicit check for forbidden topics (biology, animal trivia, generic science lists)
    is_forbid, forbid_reason = is_forbidden_content(text)
    if is_forbid:
        errors.append(f"Forbidden content policy violation: {forbid_reason}")

    # 6. Pacing & Sentence Length (max 22 words, target avg 14)
    sent_lengths = [len(get_words(s)) for s in sents]
    if sent_lengths:
        max_len = max(sent_lengths)
        if max_len > MAX_SENTENCE_WORDS:
            errors.append(f"Sentence exceeds {MAX_SENTENCE_WORDS} words ({max_len} words)")
        avg_len = sum(sent_lengths) / len(sent_lengths)
        if avg_len > AVG_SENTENCE_WORDS_TARGET + 3:
            warnings.append(f"Average sentence length is {avg_len:.1f} words (aim for <= {AVG_SENTENCE_WORDS_TARGET})")

    # Repeated sentence openers
    openers = [get_words(s)[0].lower() for s in sents if get_words(s)]
    for word in set(openers):
        if openers.count(word) >= 4 and word not in ("the", "in", "and"):
            warnings.append(f"Sentence opener '{word}' repeated {openers.count(word)} times.")

    # 7. Loop Ending (echoes hook)
    if len(sents) >= 3:
        hook_cw = get_content_words(first_sent)
        ending_cw = get_content_words(sents[-1])
        if not (hook_cw & ending_cw):
            warnings.append("Final line does not echo hook keywords for seamless replay.")
        if sents[-1].rstrip().endswith("?") and len(sents[-1].split()) < 4:
            warnings.append("Ending is a bare question.")

    # 8. Research Dossier Claim Alignment (if provided)
    if dossier is not None:
        dossier_dict = dossier if isinstance(dossier, dict) else (asdict(dossier) if hasattr(dossier, "__dict__") else {})
        claims = dossier_dict.get("verified_claims") or []
        if claims:
            # Check that at least 1 verified claim has strong semantic overlap
            found_alignment = False
            for c in claims:
                claim_txt = c.get("claim_text", "") if isinstance(c, dict) else getattr(c, "claim_text", str(c))
                claim_cw = get_content_words(claim_txt)
                text_cw = get_content_words(text)
                if len(claim_cw & text_cw) >= 2:
                    found_alignment = True
                    break
            if not found_alignment:
                warnings.append("Script does not appear to reference any verified claims from the research dossier.")

    return {
        "ok": len(errors) == 0,
        "words": n_words,
        "sentences": len(sents),
        "est_seconds": round(est_duration, 1),
        "errors": errors,
        "warnings": warnings,
        "category": detected_cat,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", nargs="?", help="Path to JSON script file")
    parser.add_argument("--text", help="Raw narration text")
    parser.add_argument("--wps", type=float, default=CALIBRATED_WORDS_PER_SECOND, help="Calibrated words per second")
    parser.add_argument("--json", action="store_true", help="Output JSON result")
    args = parser.parse_args(argv)

    try:
        if args.text:
            data = args.text
        elif args.file:
            raw = Path(args.file).read_text(encoding="utf-8")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = raw
        else:
            parser.error("Must provide either a file path or --text")
        res = validate_script(data, wps=args.wps)
    except Exception as e:
        print(f"Validation error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        status = "PASS" if res["ok"] else "FAIL"
        print(f"{status}: {res['words']} words, ~{res['est_seconds']}s (Category: {res.get('category')})")
        for err in res["errors"]:
            print(f"  [ERROR] {err}")
        for warn in res["warnings"]:
            print(f"  [WARN]  {warn}")

    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
