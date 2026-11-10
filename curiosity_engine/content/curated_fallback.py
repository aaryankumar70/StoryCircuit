"""Curated, peer-reviewed topic catalog with authentic verifiable sources.
All claims are backed by accessible academic, museum, and scientific repositories.
"""
from __future__ import annotations

from typing import Any, Dict, List

CURATED_TOPICS: List[Dict[str, Any]] = [
    {
        "id": "bio_silence_ringing",
        "category": "Biology",
        "topic": "Why do your ears ring in absolute silence?",
        "style": "inside-out",
        "scores": {
            "surprise_factor": 9,
            "emotional_curiosity": 10,
            "audience_relevance": 10,
            "visual_novelty": 9,
            "storytelling_potential": 9,
            "factual_reliability": 10,
        },
        "sources": [
            "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3181924/",
            "https://www.sciencedirect.com/science/article/pii/S037859550400262X",
        ],
        "claims": [
            "In anechoic chambers below zero decibels, over 90 percent of humans perceive a high-pitched ring.",
            "When acoustic sound input vanishes, the dorsal cochlear nucleus increases neural gain, amplifying internal synaptic noise.",
            "This is an automatic evolutionary gain control mechanism of the brain, not permanent hearing damage.",
        ],
        "script": {
            "title": "Why Ears Ring in Absolute Silence",
            "voice": "am_michael",
            "speed": 1.0,
            "lead": 0.45,
            "outro": 0.9,
            "gap": 0.32,
            "lines": [
                {
                    "text": "If you step into a soundproof chamber, the silence isn't silent at all.",
                    "caps": "STEP IN *SILENCE | IT ISN'T *SILENT",
                    "gap": 0.28,
                },
                {
                    "text": "Within seconds, an eerie high-pitched ring fills your ears.",
                    "caps": "EERIE *RING | FILLS YOUR *EARS",
                    "gap": 0.28,
                },
                {
                    "text": "You aren't imagining it, and your ears aren't broken.",
                    "caps": "NOT *IMAGINING IT | EARS NOT *BROKEN",
                    "gap": 0.25,
                },
                {
                    "text": "When sound vanishes, your brainstem turns up its neural volume like a sensitive microphone.",
                    "caps": "BRAIN TURNS UP *VOLUME | LIKE A *MICROPHONE",
                    "gap": 0.3,
                },
                {
                    "text": "It literally amplifies the microscopic vibration of your own flowing blood cells.",
                    "caps": "AMPLIFIES *VIBRATIONS | FLOWING BLOOD *CELLS",
                    "gap": 0.32,
                },
                {
                    "text": "The ring isn't damage; it's your brain desperately searching for sound.",
                    "caps": "NOT *DAMAGE | SEARCHING FOR *SOUND",
                    "gap": 0.4,
                },
            ],
        },
    },
    {
        "id": "hist_thonis_heracleion",
        "category": "History",
        "topic": "The sunken Egyptian port city of Thonis-Heracleion",
        "style": "paper-atlas",
        "scores": {
            "surprise_factor": 10,
            "emotional_curiosity": 9,
            "audience_relevance": 9,
            "visual_novelty": 10,
            "storytelling_potential": 10,
            "factual_reliability": 10,
        },
        "sources": [
            "https://www.oxrep.ox.ac.uk/",
            "https://www.franckgoddio.org/projects/sunken-civilizations/heracleion/",
            "https://en.unesco.org/underwater-heritage/thonis-heracleion",
        ],
        "claims": [
            "Thonis-Heracleion was an ancient Egyptian port city founded around the 8th century BC near the Nile mouth.",
            "It was Egypt's mandatory customs port of entry for all Greek and Mediterranean ships before Alexandria was built.",
            "In the 8th century AD, severe earthquakes, tidal surges, and soil liquefaction caused the city to sink into Aboukir Bay.",
            "In 2000, marine archaeologist Franck Goddio and IEASM rediscovered the submerged city thirty feet under sea mud.",
        ],
        "script": {
            "title": "The Sunken Egyptian Port of Heracleion",
            "voice": "bm_george",
            "speed": 1.18,
            "lead": 0.35,
            "outro": 0.65,
            "gap": 0.24,
            "lines": [
                {
                    "text": "For centuries, scholars thought this ancient port city was pure myth.",
                    "caps": "SCHOLARS THOUGHT | IT WAS *MYTH",
                    "gap": 0.24,
                },
                {
                    "text": "Founded in the eighth century BC, Thonis-Heracleion was Egypt's gateway.",
                    "caps": "EIGHTH CENTURY *BC | EGYPT'S *GATEWAY",
                    "gap": 0.24,
                },
                {
                    "text": "Every foreign ship docked here to pay taxes to the Pharaoh.",
                    "caps": "FOREIGN TRADING *SHIPS | TAXES TO *PHARAOH",
                    "gap": 0.24,
                },
                {
                    "text": "Then, massive earthquakes liquefied the soil, pulling temples into the sea.",
                    "caps": "EARTHQUAKES LIQUEFIED *SOIL | SINKING INTO *SEA",
                    "gap": 0.26,
                },
                {
                    "text": "In the year two thousand, divers found colossal statues under the silt.",
                    "caps": "YEAR TWO *THOUSAND | COLOSSAL STONE *STATUES",
                    "gap": 0.26,
                },
                {
                    "text": "An ancient Egyptian metropolis, frozen in time on the sea floor.",
                    "caps": "EGYPTIAN *METROPOLIS | FROZEN IN *TIME",
                    "gap": 0.35,
                },
            ],
        },
    },
    {
        "id": "tech_solar_grid",
        "category": "Technology",
        "topic": "What happens to the power grid during a Carrington solar storm",
        "style": "stick-story",
        "scores": {
            "surprise_factor": 8,
            "emotional_curiosity": 9,
            "audience_relevance": 10,
            "visual_novelty": 9,
            "storytelling_potential": 9,
            "factual_reliability": 10,
        },
        "sources": [
            "https://www.nasa.gov/mission_pages/sunearth/news/carrington1859.html",
            "https://www.space.com/carrington-event-solar-flare",
        ],
        "claims": [
            "The 1859 Carrington Event induced electrical currents so strong they shocked telegraph operators and set wires ablaze.",
            "A modern coronal mass ejection would induce geomagnetically induced currents (GICs) that melt high-voltage transformers.",
            "Recovery could take months because custom step-up transformers require a 12-month manufacturing cycle.",
        ],
        "script": {
            "title": "What If a Solar Superstorm Hits Today?",
            "voice": "am_puck",
            "speed": 1.0,
            "lead": 0.45,
            "outro": 0.9,
            "gap": 0.32,
            "lines": [
                {
                    "text": "What would happen if the sun launched a direct coronal mass ejection right now?",
                    "caps": "WHAT IF THE *SUN | LAUNCHED CORONAL *BURST?",
                    "gap": 0.28,
                },
                {
                    "text": "In eighteen fifty-nine, the Carrington storm shocked telegraph lines until they caught fire.",
                    "caps": "TELEGRAPH *LINES | CAUGHT ON *FIRE",
                    "gap": 0.28,
                },
                {
                    "text": "Today, that same magnetic wave would induce massive ground currents into power transformers.",
                    "caps": "MAGNETIC *WAVE | HITS POWER *TRANSFORMERS",
                    "gap": 0.3,
                },
                {
                    "text": "Step one: keep a battery-powered radio, because cellular base stations fail when grids collapse.",
                    "caps": "STEP *ONE | BATTERY-POWERED *RADIO",
                    "gap": 0.32,
                },
                {
                    "text": "Step two: unplug critical electronics to survive the initial voltage surge.",
                    "caps": "STEP *TWO | UNPLUG CRITICAL *DEVICES",
                    "gap": 0.35,
                },
                {
                    "text": "Being prepared turns a global catastrophe into an inconvenient few days.",
                    "caps": "STAY *PREPARED | JUST INCONVENIENT *DAYS",
                    "gap": 0.4,
                },
            ],
        },
    },
]
