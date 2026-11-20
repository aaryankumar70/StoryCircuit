"""CurioLoop Centralized Editorial Policy & Category Taxonomy.

Enforces CurioLoop's strict three-category identity:
  1. MYSTERY
  2. HISTORY
  3. SPACE

Explicitly forbids:
  - Human biology, anatomy, medical/health trivia, neuroscience trivia
  - Animal biology, animal trivia, nature facts
  - Generic chemistry facts, generic physics facts, generic science facts
  - Random educational trivia, listicles ("10 facts about X"), or facts without narrative

Contextual Category Validation:
  Does NOT globally ban individual words like 'galaxy', 'planet', 'astronomy',
  'black hole', or 'universe'. Instead, evaluates contextual narrative intent to
  ensure space documentaries and astronomical mysteries are accepted while
  generic science-fact lists and biology trivia are strictly rejected.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Calibrated Narration Speech Rate (derived from 8 production videos in D:\yt\output)
# ---------------------------------------------------------------------------
CALIBRATED_WORDS_PER_SECOND: float = 2.46
HARD_MIN_DURATION_SEC: float = 40.0
HARD_MAX_DURATION_SEC: float = 60.0
TARGET_MIN_DURATION_SEC: float = 42.0
TARGET_MAX_DURATION_SEC: float = 58.0

# Word budget calibrated to Kokoro at 2.46 WPS + 0.25s sentence pause allowance
HARD_WORD_MIN: int = 90
HARD_WORD_MAX: int = 148
TARGET_WORD_MIN: int = 103
TARGET_WORD_MAX: int = 140

MAX_HOOK_WORDS: int = 14
MAX_SENTENCE_WORDS: int = 22
AVG_SENTENCE_WORDS_TARGET: int = 14
PAUSE_PER_SENTENCE_SEC: float = 0.25

# ---------------------------------------------------------------------------
# Three Authorized Top-Level Editorial Categories
# ---------------------------------------------------------------------------
ALLOWED_CATEGORIES: Set[str] = {"MYSTERY", "HISTORY", "SPACE"}

SUBCATEGORY_MAPPING: Dict[str, str] = {
    # MYSTERY Subcategories
    "unexplained_events": "MYSTERY",
    "missing_expeditions": "MYSTERY",
    "lost_cities": "MYSTERY",
    "archaeological_mysteries": "MYSTERY",
    "unidentified_objects": "MYSTERY",
    "unresolved_cases": "MYSTERY",
    "strange_discoveries": "MYSTERY",
    "abandoned_places": "MYSTERY",
    "documented_anomalies": "MYSTERY",
    "historical_enigmas": "MYSTERY",
    "conflicting_evidence": "MYSTERY",
    # HISTORY Subcategories
    "forgotten_civilizations": "HISTORY",
    "ancient_empires": "HISTORY",
    "lost_kingdoms": "HISTORY",
    "historical_betrayals": "HISTORY",
    "political_intrigue": "HISTORY",
    "extraordinary_personalities": "HISTORY",
    "wars_and_turning_points": "HISTORY",
    "forgotten_expeditions": "HISTORY",
    "ancient_architecture": "HISTORY",
    "historical_secrets": "HISTORY",
    "failed_missions": "HISTORY",
    "survival_stories": "HISTORY",
    "documented_bizarre_history": "HISTORY",
    "forgotten_inventions": "HISTORY",
    "heists_and_cons": "HISTORY",
    # SPACE Subcategories
    "cosmic_mysteries": "SPACE",
    "black_holes": "SPACE",
    "neutron_stars": "SPACE",
    "exoplanets": "SPACE",
    "habitable_worlds": "SPACE",
    "fermi_paradox": "SPACE",
    "seti": "SPACE",
    "astronomical_observations": "SPACE",
    "strange_cosmic_objects": "SPACE",
    "space_missions": "SPACE",
    "astronaut_experiences": "SPACE",
    "planetary_exploration": "SPACE",
    "cosmology": "SPACE",
    "galaxies": "SPACE",
    "future_of_civilization": "SPACE",
    "deep_space_signals": "SPACE",
}

# Legacy category aliases normalized into the three top-level categories
LEGACY_CATEGORY_NORMALIZATION: Dict[str, str] = {
    "mystery": "MYSTERY",
    "mysteries": "MYSTERY",
    "unexplained events": "MYSTERY",
    "archaeology": "MYSTERY",
    "unexplained": "MYSTERY",
    "history": "HISTORY",
    "historical": "HISTORY",
    "interesting discoveries": "HISTORY",
    "survival": "HISTORY",
    "technology": "HISTORY",
    "space": "SPACE",
    "astronomy": "SPACE",
    "cosmic": "SPACE",
}

# ---------------------------------------------------------------------------
# Forbidden Topics & Patterns
# ---------------------------------------------------------------------------
FORBIDDEN_DOMAINS: List[str] = [
    "human biology",
    "animal biology",
    "anatomy",
    "medical trivia",
    "health trivia",
    "neuroscience trivia",
    "generic chemistry facts",
    "generic physics facts",
    "generic science facts",
    "random educational trivia",
    "generic fact lists without narrative",
]

# Patterns that indicate forbidden biology / anatomy / medical / animal trivia
BIOLOGY_INDICATORS = [
    r"\b(?:neuron|synapse|synaptic|dopamine|serotonin|endorphin|cortisol)\b",
    r"\b(?:cerebellum|amygdala|hippocampus|prefrontal cortex|cerebral cortex)\b",
    r"\b(?:human brain|your brain|brain tissue|brain cell|brainstem|brain)\b",
    r"\b(?:dna|rna|genome|genetic code|chromosomes?|ribosomes?)\b",
    r"\b(?:cochlea|anechoic chamber|eardrum|inner ear|tinnitus|ears? ring(?:ing)?|ringing in (?:your |the )?ears?)\b",
    r"\b(?:blood cells?|white blood cells?|red blood cells?|hemoglobin|artery|vein|blood pressure|heart rate|cardiovascular)\b",
    r"\b(?:immune system|antibodies|pathogens?|bacteria|viruses|microbes?|photosynthesis|chlorophyll)\b",
    r"\b(?:liver|kidneys?|pancreas|intestines?|stomach acid|metabolism)\b",
    r"\b(?:animal behavior|shark|sharks|greenland shark|gorilla suit|octopus|whales?|dolphins?|insects?)\b",
    r"\b(?:species of (?:animal|insect|fish|reptile|bird|shark))\b",
    r"\b(?:medical condition|symptoms of|disease cure|clinical study|medical study|caffeine affects)\b",
    r"\b(?:calories?|dietary|metabolic|digestion|organs? of the body)\b",
    r"\b(?:biology|biological|biologist|anatomy|anatomical|neuroscience|neuroscientist)\b",
]

FORBIDDEN_CATEGORY_NAMES = {
    "biology", "bio", "anatomy", "medicine", "medical", "health",
    "neuroscience", "nature", "animals", "animal", "psychology",
    "general science", "science facts", "chemistry", "physics"
}

# Patterns that indicate generic, non-narrative trivia / fact lists
GENERIC_TRIVIA_INDICATORS = [
    r"\b\d+\s+(?:facts|things|trivia|secrets|tips)\s+(?:about|you (?:didn't|never) know)\b",
    r"\b(?:ten|five|seven|three|top \d+)\s+(?:facts|things|reasons|questions)\b",
    r"\binteresting facts about\b",
    r"\brandom (?:science|educational|history|space) facts\b",
    r"\bquick facts\b",
    r"\bfacts that will blow your mind\b",
]

# ---------------------------------------------------------------------------
# Allowed Category Positive Context Markers
# ---------------------------------------------------------------------------
MYSTERY_MARKERS = [
    "vanished", "disappeared", "unsolved", "abandoned", "mystery", "enigma",
    "anomal", "strangely", "unidentified", "lost expedition", "lost city",
    "voynich", "mary celeste", "flannan", "antikythera", "archaeolog",
    "conflicting", "unanswered", "never found", "unexplained", "bizarre discovery",
]

HISTORY_MARKERS = [
    "century", "ancient", "empire", "kingdom", "dynasty", "archaeolog",
    "expedition", "soldier", "battle", "treaty", "betrayal", "pharaoh",
    "monarch", "emperor", "civilization", "ruins", "conspiracy", "heist",
    "survived", "survival", "historical", "archive", "excavation", "invention",
    "1800s", "1900s", "1700s", "bce", "ce", "in 19", "in 18", "in 17",
]

SPACE_NARRATIVE_MARKERS = [
    "astronomer", "telescope", "observatory", "radio signal", "wow signal",
    "voyager", "apollo", "mariner", "cassini", "kepler", "james webb", "hubble",
    "exoplanet", "light years", "deep space", "black hole", "neutron star",
    "event horizon", "solar flare", "supernova", "carrington event",
    "interstellar", "fermi paradox", "alien signal", "mars rover", "lunar",
    "cosmic blast", "pulsar", "galaxy", "orbit", "spacecraft", "astronaut",
    "planetary", "atmosphere of", "outer space", "deep space", "space probe",
]

# ---------------------------------------------------------------------------
# Banned Writing Openers & AI Slop Phrases
# ---------------------------------------------------------------------------
BANNED_OPENERS = [
    "in this video",
    "today we",
    "today i",
    "welcome back",
    "have you ever wondered",
    "have you ever",
    "did you know",
    "let's talk about",
    "let's dive",
    "get ready",
    "imagine a world",
    "imagine",
    "picture this",
    "what if i told you",
    "hey guys",
    "so,",
]

BANNED_PHRASES = [
    "delve",
    "tapestry",
    "in a world where",
    "little did",
    "here's the kicker",
    "but here's the thing",
    "here's the thing",
    "game-changer",
    "game changer",
    "let that sink in",
    "buckle up",
    "stay tuned",
    "like and subscribe",
    "subscribe",
    "follow for more",
    "follow for part",
    "without further ado",
    "mind-blowing",
    "mind blowing",
    "you won't believe",
    "shocking truth",
    "at the end of the day",
    "it's important to note",
    "in conclusion",
    "testament to",
    "navigate the",
    "the realm of",
    "intricate",
    "unveil",
    "fascinating",
    "incredible story",
    "rabbit hole",
    "plot twist",
    "but wait",
    "spoiler alert",
    "changed everything forever",
    "the rest is history",
    "you might be wondering",
    "it turns out that",
    "little did they know",
    "chilling reminder",
    "serves as a reminder",
    "a stark reminder",
]

WEAK_CTAS = [
    "comment below",
    "let me know in the comments",
    "what do you think",
    "share this video",
    "share with friends",
    "smash that like",
    "smash the like",
    "hit that subscribe",
    "hit subscribe",
    "subscribe to our",
    "subscribe for more",
    "subscribe to the channel",
    "please subscribe",
    "like and subscribe",
    "follow for more",
    "follow for part",
    "follow us",
    "like for part 2",
    "part 2",
]

DISCOVERY_KEYWORD_DENYLIST = [
    "biology", "neuroscience", "medicine", "health", "anatomy",
    "genetics", "chemistry facts", "physics facts", "nature facts",
    "animal facts", "psychology facts", "brain facts", "body facts",
]


# ---------------------------------------------------------------------------
# Contextual Category Validation Functions
# ---------------------------------------------------------------------------
def normalize_category_name(category: Optional[str]) -> Optional[str]:
    """Map any raw category name or alias into one of MYSTERY, HISTORY, SPACE."""
    if not category:
        return None
    raw = str(category).strip().upper()
    if raw in ALLOWED_CATEGORIES:
        return raw
    clean_lower = str(category).strip().lower()
    if clean_lower in SUBCATEGORY_MAPPING:
        return SUBCATEGORY_MAPPING[clean_lower]
    if clean_lower in LEGACY_CATEGORY_NORMALIZATION:
        return LEGACY_CATEGORY_NORMALIZATION[clean_lower]
    if "hist" in clean_lower or "ancient" in clean_lower:
        return "HISTORY"
    if "myster" in clean_lower or "unexplain" in clean_lower or "enigma" in clean_lower:
        return "MYSTERY"
    if "space" in clean_lower or "cosm" in clean_lower or "astro" in clean_lower or "planet" in clean_lower:
        return "SPACE"
    return None


normalize_category = normalize_category_name


def is_forbidden_content(text: str) -> Tuple[bool, Optional[str]]:
    """Contextually detect forbidden biology, anatomy, medical trivia, or generic fact-lists."""
    if not text:
        return False, None
    low = text.lower()

    # 1. Check generic fact list patterns
    for pat in GENERIC_TRIVIA_INDICATORS:
        if re.search(pat, low):
            return True, "Generic trivia or fact-list without documentary narrative"

    # 2. Check biology / anatomy / medical / animal trivia patterns
    for pat in BIOLOGY_INDICATORS:
        m = re.search(pat, low)
        if m:
            matched_term = m.group(0)
            return True, f"Forbidden biology/anatomy/animal trivia marker: '{matched_term}'"

    return False, None


def validate_editorial_category(
    text: str,
    declared_category: Optional[str] = None,
) -> Tuple[bool, str, str]:
    """Determine whether content belongs to MYSTERY, HISTORY, or SPACE.

    Returns:
        (is_valid, resolved_category, rejection_reason)
    """
    if not text or not text.strip():
        return False, "", "Empty topic or content"

    # Step 0: Explicitly reject forbidden declared categories
    if declared_category and str(declared_category).strip().lower() in FORBIDDEN_CATEGORY_NAMES:
        return False, "", f"Explicitly forbidden category '{declared_category}'"

    # Step 1: Reject forbidden domains (biology, medical, generic trivia)
    forbidden, reason = is_forbidden_content(text)
    if forbidden:
        return False, "", f"Forbidden content domain: {reason}"

    normalized_decl = normalize_category_name(declared_category)
    low = text.lower()

    # Step 2: Score category signals
    space_score = sum(1 for m in SPACE_NARRATIVE_MARKERS if m in low)
    history_score = sum(1 for m in HISTORY_MARKERS if m in low)
    mystery_score = sum(1 for m in MYSTERY_MARKERS if m in low)

    # Contextual check: words like 'space', 'astronomy', 'planet', 'galaxy' are ALLOWED in SPACE
    if re.search(r"\b(?:space|astronom|cosm|planet|galaxy|black hole|star|solar|orbit|lunar)\b", low):
        space_score += 2

    # Step 3: Align with declared category if compatible
    if normalized_decl == "SPACE":
        if space_score >= 1 or any(k in low for k in ("space", "cosmic", "star", "orbit", "planet", "telescope", "light year", "universe", "mission", "nasa", "esa")):
            return True, "SPACE", ""
        return True, "SPACE", ""

    if normalized_decl == "HISTORY":
        if history_score >= 1 or re.search(r"\b\d{4}\b|\bcentury\b|\bancient\b|\bwar\b|\bempire\b", low):
            return True, "HISTORY", ""
        return True, "HISTORY", ""

    if normalized_decl == "MYSTERY":
        if mystery_score >= 1 or any(k in low for k in ("mystery", "vanish", "unsolved", "secret", "strange", "clue", "found", "lost")):
            return True, "MYSTERY", ""
        return True, "MYSTERY", ""

    # Step 4: Infer category from content signals when unassigned
    best_cat = None
    scores = {"SPACE": space_score, "HISTORY": history_score, "MYSTERY": mystery_score}
    top_cat = max(scores, key=scores.get)
    if scores[top_cat] > 0:
        best_cat = top_cat

    if best_cat in ALLOWED_CATEGORIES:
        return True, best_cat, ""

    # Default fallback for narrative topics that have no forbidden markers
    return True, "MYSTERY", ""


def get_visual_style_for_category(category: str, topic_text: str = "") -> str:
    """Map top-level editorial categories to CurioLoop's visual templates.

    Preserves inside-out, paper-atlas, and stick-story without deleting any visual style.
    """
    cat = normalize_category_name(category) or "MYSTERY"
    low = (topic_text or "").lower()

    if cat == "SPACE":
        # Space telemetry, anomalies, cosmic bursts -> inside-out or stick-story
        if any(k in low for k in ("astronaut", "crew", "walk", "survived", "human")):
            return "stick-story"
        if any(k in low for k in ("telescope", "map", "1800s", "1900s", "history", "ancient")):
            return "paper-atlas"
        return "inside-out"

    if cat == "HISTORY":
        # Ancient cartography, expeditions, artifacts -> paper-atlas; personal survival -> stick-story
        if any(k in low for k in ("soldier", "escaped", "survived", "fall", "plane", "heist", "man")):
            return "stick-story"
        return "paper-atlas"

    # MYSTERY
    if any(k in low for k in ("radar", "signal", "radio", "code", "cipher", "pulse", "anomaly")):
        return "inside-out"
    if any(k in low for k in ("walked", "survivor", "crew", "passenger", "witness")):
        return "stick-story"
    return "paper-atlas"
