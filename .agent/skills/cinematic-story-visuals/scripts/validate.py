#!/usr/bin/env python3
"""
cinematic-story-visuals validator (zero dependencies).

Usage:
  python scripts/validate.py bible   <visual_bible.json>
  python scripts/validate.py episode <episode_storyboard.json> --bible <visual_bible.json> [--previous <prev_episode.json>]
  python scripts/validate.py skill   [skill_root]     # validates bundled examples + markdown links

Checks: (1) JSON Schema (Draft-07 subset; uses `jsonschema` if installed),
(2) cross-reference / continuity rules from references/serialized_visual_continuity.md.
Exit code 0 = pass, 1 = failures. Warnings never fail the run.
"""
import json, re, sys, os, argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- schema ----
def _resolve(ref, root):
    node = root
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node

def _type_ok(v, t):
    m = {"string": str, "boolean": bool, "object": dict, "array": list}
    if t == "integer": return isinstance(v, int) and not isinstance(v, bool)
    if t == "number": return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "null": return v is None
    return isinstance(v, m[t])

def _check(v, s, root, path, errs):
    if "$ref" in s:
        return _check(v, _resolve(s["$ref"], root), root, path, errs)
    if "const" in s and v != s["const"]:
        errs.append(f"{path}: must equal {s['const']!r}")
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: {v!r} not in {s['enum']}")
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_type_ok(v, t) for t in ts):
            errs.append(f"{path}: expected {'/'.join(ts)}, got {type(v).__name__}")
            return
    if isinstance(v, str):
        if "minLength" in s and len(v) < s["minLength"]: errs.append(f"{path}: shorter than {s['minLength']}")
        if "pattern" in s and not re.search(s["pattern"], v): errs.append(f"{path}: {v!r} !~ {s['pattern']}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in s and v < s["minimum"]: errs.append(f"{path}: {v} < {s['minimum']}")
        if "maximum" in s and v > s["maximum"]: errs.append(f"{path}: {v} > {s['maximum']}")
    if isinstance(v, dict):
        for r in s.get("required", []):
            if r not in v: errs.append(f"{path}: missing required '{r}'")
        for k, sub in s.get("properties", {}).items():
            if k in v: _check(v[k], sub, root, f"{path}.{k}", errs)
    if isinstance(v, list):
        if "minItems" in s and len(v) < s["minItems"]: errs.append(f"{path}: fewer than {s['minItems']} items")
        if "maxItems" in s and len(v) > s["maxItems"]: errs.append(f"{path}: more than {s['maxItems']} items")
        if "items" in s:
            for i, it in enumerate(v): _check(it, s["items"], root, f"{path}[{i}]", errs)

def schema_errors(data, schema):
    try:
        import jsonschema
        v = jsonschema.Draft7Validator(schema)
        return [f"{'.'.join(map(str, e.absolute_path)) or '$'}: {e.message}" for e in v.iter_errors(data)]
    except ImportError:
        errs = []; _check(data, schema, schema, "$", errs); return errs

# ----------------------------------------------------------- continuity ----
def bible_index(b):
    chars = {c["character_id"]: {s["state_id"] for s in c["states"]} for c in b["characters"]}
    locs = {l["location_id"]: {v["variant_id"] for v in l["variants"]} for l in b["locations"]}
    return chars, locs

def bible_rules(b):
    errs, warns = [], []
    ids = [c["character_id"] for c in b["characters"]]
    if len(ids) != len(set(ids)): errs.append("duplicate character_id")
    lids = [l["location_id"] for l in b["locations"]]
    if len(lids) != len(set(lids)): errs.append("duplicate location_id")
    for c in b["characters"]:
        sids = [s["state_id"] for s in c["states"]]
        if len(sids) != len(set(sids)): errs.append(f"{c['character_id']}: duplicate state_id")
        for s in c["states"]:
            if not s.get("locked_traits"): warns.append(f"{c['character_id']}/{s['state_id']}: no locked_traits (consistency risk)")
    chars, locs = bible_index(b)
    for e in b.get("continuity_ledger", []):
        st = e["closing_visual_state"]
        if st["location_id"] not in locs or st["variant_id"] not in locs.get(st["location_id"], ()):
            errs.append(f"ledger ep{e['episode_number']}: unknown location/variant {st['location_id']}/{st['variant_id']}")
        for cs in st.get("character_states", []):
            if cs["state_id"] not in chars.get(cs["character_id"], ()):
                errs.append(f"ledger ep{e['episode_number']}: unknown character state {cs['character_id']}/{cs['state_id']}")
    eps = [e["episode_number"] for e in b.get("continuity_ledger", [])]
    if eps != sorted(set(eps)): errs.append("continuity_ledger episode_numbers must be unique and ascending")
    return errs, warns

def episode_rules(ep, b, prev=None):
    errs, warns = [], []
    chars, locs = bible_index(b)
    if ep["series_id"] != b["series_id"]: errs.append("series_id differs from bible")
    if ep["bible_version"] != b.get("bible_version", 1): warns.append(f"bible_version {ep['bible_version']} != bible {b.get('bible_version', 1)}")
    if ep["profile"] != b["profile"]: errs.append("profile differs from bible")
    sc = ep["scenes"]; ids = [s["scene_id"] for s in sc]
    if len(ids) != len(set(ids)): errs.append("duplicate scene_id")
    pref = f"ep{ep['episode_number']:02d}_"
    for i in ids:
        if not i.startswith(pref): errs.append(f"{i}: scene_id must start with {pref}")
    last_end = 0.0
    for s in sc:
        sid = s["scene_id"]; n = s["narration"]
        if n["end_s"] <= n["start_s"]: errs.append(f"{sid}: narration end_s <= start_s")
        if n["start_s"] + 0.25 < last_end: errs.append(f"{sid}: narration overlaps previous scene")
        if n["start_s"] - last_end > 1.5: warns.append(f"{sid}: {n['start_s']-last_end:.1f}s gap in narration coverage")
        last_end = max(last_end, n["end_s"])
        if s["location_id"] not in locs: errs.append(f"{sid}: unknown location_id {s['location_id']}")
        elif s["variant_id"] not in locs[s["location_id"]]: errs.append(f"{sid}: unknown variant_id {s['variant_id']} for {s['location_id']}")
        for c in s["characters"]:
            if c["character_id"] not in chars: errs.append(f"{sid}: unknown character_id {c['character_id']}")
            elif c["state_id"] not in chars[c["character_id"]]: errs.append(f"{sid}: unknown state_id {c['state_id']} for {c['character_id']}")
        cm = s["camera_movement"]
        if cm["type"] == "static" and cm["intensity"] != "none": errs.append(f"{sid}: static camera must have intensity 'none'")
        if cm["type"] != "static" and cm["intensity"] == "none": errs.append(f"{sid}: moving camera cannot have intensity 'none'")
        if cm["intensity"] == "strong" and s["tension_level"] < 7: warns.append(f"{sid}: strong movement at tension {s['tension_level']} - justify in rationale")
        if "start_scale" in cm and "end_scale" in cm and abs(cm["end_scale"] - cm["start_scale"]) > 0.35: warns.append(f"{sid}: scale change > 0.35 is visibly fast for a Short")
        if s["narrative_mode"] in ("flashback", "remembered_narration"):
            for c in s["characters"]:
                if c["presence"] == "on_screen" and "child" not in c["state_id"] and "young" not in c["state_id"] and "past" not in c["state_id"]:
                    warns.append(f"{sid}: {s['narrative_mode']} scene uses state '{c['state_id']}' - confirm it is the correct era state")
    # transitions of last scene
    if sc and sc[-1]["transition_out"]["type"] not in ("dip_to_black", "slow_dissolve", "hard_cut"):
        warns.append("last scene transition is unusual for an episode end")
    # progression coverage
    covered = [x for p in ep["visual_progression"] for x in p["scene_ids"]]
    for x in covered:
        if x not in ids: errs.append(f"visual_progression references unknown scene {x}")
    for i in ids:
        if i not in covered: warns.append(f"{i} not covered by any visual_progression phase")
    # opening/closing vs bible
    for k in ("opening_visual", "closing_visual"):
        v = ep[k]
        if v["location_id"] not in locs or v["variant_id"] not in locs.get(v["location_id"], ()):
            errs.append(f"{k}: unknown location/variant")
    if sc:
        if ep["opening_visual"]["location_id"] != sc[0]["location_id"]: warns.append("opening_visual location differs from first scene")
        if ep["closing_visual"]["location_id"] != sc[-1]["location_id"]: warns.append("closing_visual location differs from last scene")
        if sc[-1]["narration"]["end_s"] > ep["target_duration_seconds"] + 3: warns.append("narration runs past target_duration_seconds")
    # episode-to-episode
    if ep["episode_number"] > 1 and ep["opening_visual"].get("continues_from_episode") is None:
        warns.append("episode > 1 without opening_visual.continues_from_episode")
    led = {e["episode_number"]: e for e in b.get("continuity_ledger", [])}
    cf = ep["opening_visual"].get("continues_from_episode")
    if cf and cf in led:
        st = led[cf]["closing_visual_state"]
        if (ep["opening_visual"]["location_id"], ep["opening_visual"]["variant_id"]) != (st["location_id"], st["variant_id"]):
            warns.append(f"opening location/variant differs from ep{cf} ledger closing state - allowed only with a motivated transition (document in continuity_notes)")
    if prev:
        if prev["episode_number"] != ep["episode_number"] - 1: warns.append("--previous is not episode N-1")
        pl = prev["closing_visual"]; ol = ep["opening_visual"]
        if (pl["location_id"], pl["variant_id"]) != (ol["location_id"], ol["variant_id"]) and not ep.get("continuity_notes"):
            errs.append("opening differs from previous closing and no continuity_notes explain it")
    return errs, warns

# ------------------------------------------------------------- markdown ----
def link_errors(root):
    errs = []
    for dp, _, fs in os.walk(root):
        for f in fs:
            if not f.endswith(".md"): continue
            p = os.path.join(dp, f); text = open(p, encoding="utf-8").read()
            text_nocode = re.sub(r"```.*?```", "", text, flags=re.S)
            for m in re.finditer(r"\]\(([^)#\s]+)(#[^)]*)?\)", text_nocode):
                t = m.group(1)
                if re.match(r"^(https?:|mailto:)", t): continue
                if not os.path.exists(os.path.normpath(os.path.join(dp, t))):
                    errs.append(f"{os.path.relpath(p, root)}: broken link -> {t}")
    return errs

# ----------------------------------------------------------------- main ----
def load(p): 
    with open(p, encoding="utf-8") as f: return json.load(f)

def report(name, errs, warns):
    for w in warns: print(f"  WARN  {name}: {w}")
    for e in errs: print(f"  FAIL  {name}: {e}")
    print(f"{'PASS' if not errs else 'FAIL'}  {name}  ({len(errs)} errors, {len(warns)} warnings)")
    return not errs

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("mode", choices=["bible", "episode", "skill"]); ap.add_argument("path", nargs="?")
    ap.add_argument("--bible"); ap.add_argument("--previous"); a = ap.parse_args()
    S = lambda n: load(os.path.join(ROOT, "schemas", n))
    ok = True
    if a.mode == "bible":
        b = load(a.path); e = schema_errors(b, S("visual_bible.schema.json"))
        e2, w = ([], []) if e else bible_rules(b); ok = report(a.path, e + e2, w)
    elif a.mode == "episode":
        if not a.bible: sys.exit("--bible is required")
        ep, b = load(a.path), load(a.bible)
        e = schema_errors(ep, S("episode_storyboard.schema.json")) + [f"(bible) {x}" for x in schema_errors(b, S("visual_bible.schema.json"))]
        e2, w = ([], []) if e else episode_rules(ep, b, load(a.previous) if a.previous else None)
        ok = report(a.path, e + e2, w)
    else:
        root = a.path or ROOT
        bp = os.path.join(root, "examples", "visual_bible_example.json"); ep = os.path.join(root, "examples", "episode_storyboard_example.json")
        b = load(bp); e = schema_errors(b, S("visual_bible.schema.json")); e2, w = ([], []) if e else bible_rules(b)
        ok &= report("examples/visual_bible_example.json", e + e2, w)
        x = load(ep); e = schema_errors(x, S("episode_storyboard.schema.json")); e2, w = ([], []) if e else episode_rules(x, b)
        ok &= report("examples/episode_storyboard_example.json", e + e2, w)
        sc = os.path.join(root, "templates", "scene_specification_template.json")
        if os.path.exists(sc):
            try: load(sc); print("PASS  templates/scene_specification_template.json (valid JSON)")
            except Exception as ex: print("FAIL  scene template:", ex); ok = False
        le = link_errors(root); ok &= report("markdown links", le, [])
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
