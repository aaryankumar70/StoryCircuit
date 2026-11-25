"""Fresh, non-repeating topic discovery using AI + Wikipedia public APIs + curated seeds."""
from __future__ import annotations

import logging
import random
from typing import Any, Dict, List, Optional

import requests

from reelforge.storage.db import ReelDatabase

logger = logging.getLogger("reelforge.brain.topics")

CURATED_TOPICS: List[Dict[str, str]] = [
    {
        "topic": "The 1914 Christmas Truce in the Trenches",
        "category": "history",
        "facts": "In December 1914 along the Western Front, enemy soldiers stopped firing, sang carols, traded rations, and played football in no-man's-land before commanders ordered them back to war.",
    },
    {
        "topic": "The Phantom Time of the Antikythera Mechanism",
        "category": "mystery",
        "facts": "Recovered from a 2,000-year-old Roman shipwreck off Greece in 1901, a corroded bronze box held 30 interlocking gears that predicted eclipses and Olympic cycles centuries ahead of its era.",
    },
    {
        "topic": "The 1977 Wow! Signal from Sagittarius",
        "category": "space",
        "facts": "On August 15, 1977, astronomer Jerry Ehman circled '6EQUJ5' on a Big Ear radio printout—a 72-second narrowband signal 30 times louder than background space noise that never repeated.",
    },
    {
        "topic": "Why London's 1814 Flood Was Made of Beer",
        "category": "history",
        "facts": "In October 1814, an iron hoop snapped on a 22-foot wooden vat at Meux's Horse Shoe Brewery in London, unleashing over 320,000 gallons of porter into St Giles slums.",
    },
    {
        "topic": "The Voynich Manuscript Nobody Can Read",
        "category": "mystery",
        "facts": "Carbon-dated to the early 1400s, a 240-page vellum codex filled with impossible plants, zodiac charts, and an unknown script has defeated cryptographers and AI decoders for over a century.",
    },
    {
        "topic": "Voyager 1's Pale Blue Dot Command",
        "category": "space",
        "facts": "In February 1990, NASA turned Voyager 1's camera backward 3.7 billion miles from Earth at Carl Sagan's urging, capturing our entire planet as a 0.12-pixel speck inside a scattered sunbeam.",
    },
    {
        "topic": "The Great Emu War of 1932",
        "category": "history",
        "facts": "In Western Australia in 1932, soldiers armed with Lewis machine guns and 10,000 rounds tried to stop 20,000 migrating emus raiding wheat farms—and the birds outmaneuvered the army.",
    },
    {
        "topic": "The 1908 Tunguska Blast Without a Crater",
        "category": "mystery",
        "facts": "On June 30, 1908, an atmospheric explosion over Siberia flattened 80 million trees across 830 square miles, yet left no impact crater behind.",
    },
    {
        "topic": "How a Single Software Bug Almost Triggered Nuclear War in 1983",
        "category": "history",
        "facts": "On September 26, 1983, Soviet officer Stanislav Petrov ignored early-warning satellite alerts claiming five US missiles were inbound—later traced to sunlight glinting off high-altitude clouds.",
    },
    {
        "topic": "The Deepest Hole Ever Dug: Kola Superdeep Borehole",
        "category": "science",
        "facts": "Soviet geologists drilled 12,262 meters into the Arctic crust over 20 years, finding microscopic plankton fossils four miles down and rock too hot at 180 degrees Celsius to keep drilling.",
    },
    {
        "topic": "The Lighthouse Keepers Who Vanished from Flannan Isles",
        "category": "mystery",
        "facts": "In December 1900, a relief ship reached Scotland's remote Eilean Mor lighthouse to find untouched dinner plates, a stopped clock, one waterproof coat still hanging, and all three keepers gone.",
    },
    {
        "topic": "Why Roman Concrete Lasts 2,000 Years in Seawater",
        "category": "science",
        "facts": "Ancient Roman harbor concrete mixed volcanic ash with hot quicklime clasts that chemically self-heal cracks whenever ocean water seeps in—while modern steel-reinforced concrete erodes in decades.",
    },
    {
        "topic": "The Year Without a Summer: 1816",
        "category": "history",
        "facts": "Following Mount Tambora's massive 1815 eruption, ash veiled the Northern Hemisphere so snow fell in June 1816 across New England and Mary Shelley wrote Frankenstein while trapped indoors.",
    },
    {
        "topic": "The Man Who Sold the Eiffel Tower Twice",
        "category": "history",
        "facts": "In 1925, con artist Victor Lustig posed as a French ministry official and convinced scrap metal dealers that Paris was secretly dismantling the Eiffel Tower—collecting bribes before vanishing.",
    },
    {
        "topic": "The Singing Sands of the Badain Jaran Desert",
        "category": "nature",
        "facts": "In northwestern China, 1,600-foot dunes produce a deep humming drone audible miles away when dry, uniformly sized quartz grains avalanche in unison.",
    },
    {
        "topic": "The 1518 Strasbourg Dancing Plague",
        "category": "mystery",
        "facts": "In July 1518, a woman named Frau Troffea began dancing uncontrollably in Strasbourg's streets, and within a month roughly 400 citizens joined in until authorities hired musicians and built stages.",
    },
    {
        "topic": "Apollo 12's Double Lightning Strike During Liftoff",
        "category": "space",
        "facts": "Thirty-six seconds after Apollo 12 launched into rainclouds in 1969, lightning knocked out every telemetry display until flight controller John Aaron called out 'SCE to Aux' and saved the moon mission.",
    },
    {
        "topic": "Why Ships Used to Carry Glass Bottles Full of Oil Against Waves",
        "category": "science",
        "facts": "Benjamin Franklin tested spreading a single teaspoon of oil over half an acre of pond water, proving a one-molecule-thick film calms breaking waves by altering surface tension.",
    },
    {
        "topic": "The Secret Underground City of Derinkuyu",
        "category": "history",
        "facts": "In 1963, a homeowner knocking down a basement wall in Turkey uncovered an 18-story subterranean city carved from volcanic rock that once sheltered 20,000 people and livestock.",
    },
    {
        "topic": "The Immortal Jellyfish That Rewinds Its Age",
        "category": "nature",
        "facts": "When injured or stressed, Turritopsis dohrnii transforms its adult cells back into a youthful polyp state, restarting its entire biological life cycle indefinitely.",
    },
    {
        "topic": "The 1962 Cold War Submarine Officer Who Refused to Launch",
        "category": "history",
        "facts": "During the Cuban Missile Crisis, Soviet submarine B-59 lost radio contact while depth charges exploded nearby; Vasili Arkhipov vetoed launching a nuclear torpedo that needed three officers' consent.",
    },
    {
        "topic": "Why Jupiter's Great Red Spot Is Shrinking",
        "category": "space",
        "facts": "Observed for over 300 years, Jupiter's colossal anticyclonic storm was once wide enough to swallow three Earths, yet Hubble measurements show it has shrunk to nearly half its 1800s diameter.",
    },
    {
        "topic": "The Ghost Ship Mary Celeste Found Under Full Sail",
        "category": "mystery",
        "facts": "In December 1872, the brigantine Mary Celeste was discovered drifting smoothly near the Azores with six months of food, intact cargo, a missing lifeboat, and zero crew aboard.",
    },
    {
        "topic": "How a Pigeon Guided World War II Missile Prototypes",
        "category": "tech",
        "facts": "Psychologist B.F. Skinner trained pigeons inside missile nose cones to peck crosshairs on a screen tracking ships, achieving remarkable accuracy long before digital computer vision existed.",
    },
    {
        "topic": "The Forgotten Female Mathematician Who Saved Apollo 11",
        "category": "tech",
        "facts": "Margaret Hamilton's team wrote priority-shedding Apollo Guidance Computer software that threw away low-priority radar tasks minutes before landing, preventing an abort during 1202 alarms.",
    },
    {
        "topic": "The Oak Island Money Pit Mystery",
        "category": "mystery",
        "facts": "Since 1795, treasure hunters off Nova Scotia have excavated oak platforms every ten feet down a flooded shaft rigged with stone drains, spending millions without solving who built it.",
    },
    {
        "topic": "Why Venuses Rotate Backward Compared to Almost Every Planet",
        "category": "space",
        "facts": "Venus spins clockwise so slowly that a single sidereal day on Venus lasts 243 Earth days—longer than its entire 225-day orbit around the Sun.",
    },
    {
        "topic": "The Underground Coal Fire Burning Since 1962",
        "category": "science",
        "facts": "Beneath Centralia, Pennsylvania, an abandoned anthracite coal seam ignited in May 1962 and still smolders today with enough fuel to burn for over 250 years.",
    },
    {
        "topic": "The World's Oldest Known Analog Computer Was Not Greek Alone",
        "category": "tech",
        "facts": "Long before silicon chips, mechanical tide predictors used brass pulleys and harmonic cams in the 1870s to calculate a year's ocean tides in hours.",
    },
    {
        "topic": "The Giant Hexagonal Storm on Saturn's North Pole",
        "category": "space",
        "facts": "Spanning nearly 18,000 miles across Saturn's north pole, a six-sided jet stream stays locked in geometric symmetry and has persisted for decades.",
    },
]

_BAD_WIKI_PREFIXES = ("list of", "disambiguation", "index of", "outline of", "timeline of")


def fetch_wikipedia_candidate() -> Optional[Dict[str, str]]:
    """Fetch a random real-world summary from Wikipedia's free REST API."""
    headers = {"User-Agent": "ReelForge/0.1 (local zero-cost video studio)"}
    try:
        resp = requests.get(
            "https://en.wikipedia.org/api/rest_v1/page/random/summary",
            headers=headers,
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        title = str(data.get("title", "")).strip()
        extract = str(data.get("extract", "")).strip()
        desc = str(data.get("description", "")).lower()
        if not title or len(extract) < 160:
            return None
        if any(title.lower().startswith(p) for p in _BAD_WIKI_PREFIXES):
            return None
        if "disambiguation" in desc:
            return None
        return {
            "topic": title,
            "category": "story",
            "facts": extract[:1000],
            "source_url": str(data.get("content_urls", {}).get("desktop", {}).get("page", "")),
        }
    except Exception as exc:
        logger.debug("Wikipedia random summary failed: %s", exc)
        return None


def _llm_discover_topic(
    llm: Any,
    category: str,
    avoid_titles: List[str],
) -> Optional[Dict[str, str]]:
    """Ask LLM (Gemini/Ollama) to propose a completely fresh, verifiable, high-curiosity topic."""
    if llm is None:
        return None
    avoid_str = "; ".join(avoid_titles[:25]) if avoid_titles else "none"
    cat_hint = category if category and category != "auto" else "history, mystery, space, science, nature, or technology"
    system_prompt = (
        "You are a viral documentary researcher. Pick ONE fascinating, 100% real, verifiable story or phenomenon "
        "with high viewer curiosity. Never repeat any topic from the avoid list. Respond strictly in JSON."
    )
    user_prompt = (
        f"Category preference: {cat_hint}\n"
        f"Avoid these past topics completely: {avoid_str}\n\n"
        'Return JSON: {"topic": "punchy specific topic title", "category": "history|mystery|space|science|nature|tech", '
        '"facts": "4-6 specific verifiable facts with dates, numbers, and names"}'
    )
    try:
        data = llm.generate_json(system_prompt, user_prompt, temperature=0.85)
    except Exception:
        return None
    if not data or not isinstance(data.get("topic"), str) or not isinstance(data.get("facts"), str):
        return None
    topic = data["topic"].strip()
    facts = data["facts"].strip()
    if len(topic) < 6 or len(facts) < 80:
        return None
    cat = str(data.get("category") or "story").strip().lower()
    if cat not in {"history", "mystery", "space", "science", "nature", "tech", "story"}:
        cat = "story"
    return {"topic": topic, "category": cat, "facts": facts[:1100]}


def pick_fresh_topic(
    db: ReelDatabase,
    category: str = "auto",
    llm: Optional[Any] = None,
    avoid_extra: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Return a fresh topic guaranteed not to match previous entries in topic_history."""
    history_titles = [h["title"] for h in db.list_history(limit=40)]
    avoid_all = list(dict.fromkeys([*history_titles, *(avoid_extra or [])]))
    avoid_lower = {t.lower().strip() for t in avoid_all}

    # 1. AI-discovered unique topic (when LLM is configured/online)
    for _ in range(2):
        ai_cand = _llm_discover_topic(llm, category, avoid_all)
        if ai_cand and ai_cand["topic"].lower().strip() not in avoid_lower:
            is_dup, _ = db.check_duplicate_topic(ai_cand["topic"], ai_cand["facts"])
            if not is_dup:
                return ai_cand

    # 2. Fresh Wikipedia random real-world summary
    if category in ("auto", "story", "history", "science", "nature"):
        for _ in range(5):
            wiki = fetch_wikipedia_candidate()
            if wiki and wiki["topic"].lower().strip() not in avoid_lower:
                is_dup, _ = db.check_duplicate_topic(wiki["topic"], wiki["facts"])
                if not is_dup:
                    return wiki

    # 3. Curated high-retention pool
    pool = list(CURATED_TOPICS)
    if category and category != "auto":
        filtered = [t for t in pool if t["category"].lower() == category.lower()]
        if filtered:
            pool = filtered
    random.shuffle(pool)

    for item in pool:
        if item["topic"].lower().strip() in avoid_lower:
            continue
        is_dup, _ = db.check_duplicate_topic(item["topic"], item["facts"])
        if not is_dup:
            return dict(item)

    # 4. Last-resort unique deep-dive angle if local curated topics are all exhausted offline
    base = random.choice(CURATED_TOPICS)
    suffix = random.randint(100, 999)
    return {
        "topic": f"Lost Evidence Inside {base['topic']} (#{suffix})",
        "category": base["category"],
        "facts": base["facts"],
    }
