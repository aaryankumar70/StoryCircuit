#!/usr/bin/env python3
"""Deterministic script gate for 40-60 s YouTube Shorts narration. Stdlib only.

Usage:
  python validate_script.py script.json [--wps 2.6] [--json]
  python validate_script.py --text "Full narration..." [--wps 2.6]

Accepted JSON: a string, or an object with one of
  script / narration / text   (string)
  beats / segments / scenes   (list of strings or objects with text|narration|line|voiceover)
optional: hook, title.
Exit code 0 = pass (warnings allowed), 1 = errors, 2 = bad input.
Import use: from validate_script import validate; validate(data, wps=2.6)
"""
import argparse, json, re, sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
POLICY_PATH = SKILL_DIR / "resources" / "niche_policy.json"
PHRASES_PATH = SKILL_DIR / "resources" / "banned_phrases.json"

HARD_MIN_S, HARD_MAX_S = 40.0, 60.0     # errors outside this
TARGET_MIN_S, TARGET_MAX_S = 42.0, 58.0  # warnings outside this
PAUSE_PER_SENTENCE_S = 0.25
MAX_HOOK_WORDS = 14
MAX_SENTENCE_WORDS = 22
AVG_SENTENCE_WORDS = 14
STOP = set("the a an and or but of to in on at for with from by is are was were be been it its this that "
           "he she they them his her their you your i we our as so if then than not no just into out up".split())


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _term_regex(terms):
    parts = []
    for t in terms:
        t = t.strip().lower()
        if t:
            parts.append(re.escape(t) + r"(?:s|es)?")
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.I) if parts else None


def extract(data):
    """Return (title, hook, beats, full_text)."""
    title = hook = ""
    beats = []
    if isinstance(data, str):
        text = data
    elif isinstance(data, dict):
        title = str(data.get("title", "") or "")
        hook = str(data.get("hook", "") or "")
        text = ""
        for key in ("beats", "segments", "scenes"):
            if isinstance(data.get(key), list) and data[key]:
                for b in data[key]:
                    if isinstance(b, str):
                        beats.append(b)
                    elif isinstance(b, dict):
                        for k in ("text", "narration", "line", "voiceover"):
                            if b.get(k):
                                beats.append(str(b[k]))
                                break
                text = " ".join(beats)
                break
        if not text:
            for key in ("script", "narration", "text"):
                if data.get(key):
                    text = str(data[key])
                    break
    else:
        raise ValueError("unsupported input")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise ValueError("no narration text found")
    return title, hook, beats, text


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def words(text):
    return re.findall(r"[A-Za-z0-9$%'’\-]+", text)


def content_words(text):
    return {w.lower() for w in words(text) if w.lower() not in STOP and len(w) > 2}


def validate(data, wps=2.6):
    policy, phrases = _load(POLICY_PATH), _load(PHRASES_PATH)
    title, hook, beats, text = extract(data)
    sents = sentences(text)
    n_words = len(words(text))
    est = n_words / wps + PAUSE_PER_SENTENCE_S * len(sents)
    errors, warnings = [], []

    # duration
    if est < HARD_MIN_S or est > HARD_MAX_S:
        errors.append(f"estimated duration {est:.0f}s outside hard range {HARD_MIN_S:.0f}-{HARD_MAX_S:.0f}s "
                      f"({n_words} words at {wps} wps)")
    elif est < TARGET_MIN_S or est > TARGET_MAX_S:
        warnings.append(f"estimated duration {est:.0f}s outside target {TARGET_MIN_S:.0f}-{TARGET_MAX_S:.0f}s")

    # hook
    first = hook.strip() or sents[0]
    if len(words(first)) > MAX_HOOK_WORDS:
        errors.append(f"hook is {len(words(first))} words (max {MAX_HOOK_WORDS}): '{first[:70]}'")
    low_first = first.lower()
    for op in phrases["banned_openers"]:
        if low_first.startswith(op):
            errors.append(f"weak opener '{op}'")
            break
    if not (re.search(r"\d", first) or re.search(r"\b[A-Z][a-z]+", first[1:])):
        warnings.append("hook has no number or proper noun; concrete hooks hold viewers better")

    # slop
    low = text.lower()
    hits = sorted({p for p in phrases["banned_phrases"] if re.search(r"\b" + re.escape(p), low)})
    for h in hits:
        errors.append(f"banned phrase: '{h}'")
    for c in phrases.get("weak_ctas", []):
        if c in low:
            errors.append(f"weak CTA: '{c}'")

    # topic policy
    strong = _term_regex(policy["strong_deny"])
    soft = _term_regex(policy["soft_deny"])
    for corpus in (title, text):
        if strong:
            m = sorted({x.group(0).lower() for x in strong.finditer(corpus)})
            for term in m:
                errors.append(f"denied topic term (biology/science policy): '{term}'")
    if soft:
        m = sorted({x.group(0).lower() for x in soft.finditer(text)})
        if m:
            warnings.append("possible science wording (check context): " + ", ".join(m))

    # pacing
    lens = [len(words(s)) for s in sents]
    if lens and max(lens) > MAX_SENTENCE_WORDS:
        errors.append(f"sentence too long ({max(lens)} words, max {MAX_SENTENCE_WORDS})")
    if lens and sum(lens) / len(lens) > AVG_SENTENCE_WORDS:
        warnings.append(f"average sentence {sum(lens)/len(lens):.1f} words; aim for <= {AVG_SENTENCE_WORDS}")
    for b in beats:
        if len(words(b)) > 30:
            warnings.append(f"beat too long for one scene ({len(words(b))} words)")
    openers = [words(s)[0].lower() for s in sents if words(s)]
    for w in set(openers):
        if openers.count(w) >= 4 and w not in ("and",):
            warnings.append(f"{openers.count(w)} sentences start with '{w}'")

    # specificity
    specifics = len(re.findall(r"\d[\d,\.]*", text)) + len(re.findall(r"(?<=[a-z,] )[A-Z][a-z]{2,}", text))
    if specifics < 3:
        warnings.append("few concrete specifics (names, places, numbers); add some")

    # loop ending
    if len(sents) >= 3:
        if not (content_words(sents[-1]) & content_words(first)):
            warnings.append("last line does not echo the hook; Shorts that loop get rewatched")
        if sents[-1].rstrip().endswith("?") and len(sents[-1].split()) < 4:
            warnings.append("ending is a bare question")

    return {
        "ok": not errors, "words": n_words, "sentences": len(sents),
        "est_seconds": round(est, 1), "errors": errors, "warnings": warnings,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?")
    ap.add_argument("--text")
    ap.add_argument("--wps", type=float, default=2.6, help="measured narration words per second")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.text:
            data = a.text
        elif a.file:
            raw = Path(a.file).read_text(encoding="utf-8")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = raw
        else:
            ap.error("give a file or --text")
        res = validate(data, a.wps)
    except (OSError, ValueError) as e:
        print(f"input error: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"{'PASS' if res['ok'] else 'FAIL'}  {res['words']} words, ~{res['est_seconds']}s")
        for e in res["errors"]:
            print("  ERROR:", e)
        for w in res["warnings"]:
            print("  warn: ", w)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
