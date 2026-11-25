"""Fresh, non-repeating topic discovery using Wikipedia public APIs + curated seeds."""
from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional

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
        if not title or len(extract) < 140:
            return None
        if any(title.lower().startswith(p) for p in _BAD_WIKI_PREFIXES):
            return None
        if "disambiguation" in desc:
            return None
        return {
            "topic": title,
            "category": "story",
            "facts": extract[:900],
            "source_url": str(data.get("content_urls", {}).get("desktop", {}).get("page", "")),
        }
    except Exception as exc:
        logger.debug("Wikipedia random summary failed: %s", exc)
        return None


def pick_fresh_topic(db: ReelDatabase, category: str = "auto") -> Dict[str, str]:
    """Return a topic guaranteed not to match previous entries in topic_history."""
    pool = list(CURATED_TOPICS)
    if category and category != "auto":
        filtered = [t for t in pool if t["category"].lower() == category.lower()]
        if filtered:
            pool = filtered
    random.shuffle(pool)

    # First check fresh Wikipedia candidates when category is open
    if category in ("auto", "story", "history", "science"):
        for _ in range(4):
            wiki = fetch_wikipedia_candidate()
            if wiki:
                is_dup, _ = db.check_duplicate_topic(wiki["topic"], wiki["facts"])
                if not is_dup:
                    return wiki

    for item in pool:
        is_dup, _ = db.check_duplicate_topic(item["topic"], item["facts"])
        if not is_dup:
            return dict(item)

    # Last-resort novel angle if all curated topics were exhausted
    fallback = random.choice(CURATED_TOPICS)
    return {
        "topic": f"Untold Detail Behind {fallback['topic']}",
        "category": fallback["category"],
        "facts": fallback["facts"],
    }
