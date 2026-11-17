"""Curated Topic Archive (Deprecated / Archived Categories).

Preserves historical entries that do not fit the active CurioLoop editorial policy
(Biology, Psychology, Nature, Animal trivia) for testing or regression purposes.
These entries are NOT served to the autonomous production pipeline.
"""
from __future__ import annotations

from typing import Any, Dict, List

ARCHIVED_TOPICS: List[Dict[str, Any]] = [
    {
        "id": "bio_silence_ringing",
        "category": "Biology",
        "topic": "Why do your ears ring in absolute silence?",
        "style": "inside-out",
        "evidence_type": "scientific_study",
        "discovery_origin": "archived_research",
        "archived_reason": "Biology and anatomy trivia banned under 2026 editorial policy.",
        "sources": [
            "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3181924/",
            "https://www.sciencedirect.com/science/article/pii/S037859550400262X",
        ],
        "claims": [
            "In anechoic chambers below zero decibels, over 90 percent of humans perceive phantom ringing.",
            "When acoustic input vanishes, the dorsal cochlear nucleus increases internal neural gain.",
        ],
    },
    {
        "id": "bio_greenland_shark",
        "category": "Nature",
        "topic": "A blind Arctic shark born in the 1600s may still be swimming today",
        "style": "inside-out",
        "evidence_type": "scientific_study",
        "discovery_origin": "archived_research",
        "archived_reason": "Animal trivia banned under 2026 editorial policy.",
        "sources": [
            "https://www.science.org/doi/10.1126/science.aaf1703",
        ],
        "claims": [
            "Radiocarbon dating of Greenland shark eye lenses reveals lifespans exceeding 390 years.",
        ],
    },
    {
        "id": "psych_invisible_gorilla",
        "category": "Psychology",
        "topic": "Why half the people counting basketball passes completely miss someone in a gorilla suit",
        "style": "inside-out",
        "evidence_type": "scientific_study",
        "discovery_origin": "archived_research",
        "archived_reason": "Psychology experiment trivia replaced by documentary mystery/history focus.",
        "sources": [
            "https://www.ncbi.nlm.nih.gov/pubmed/10594943",
        ],
        "claims": [
            "In selective attention tests, approximately 50 percent of participants fail to notice an unexpected salient event.",
        ],
    },
    {
        "id": "psych_kuleshov_face",
        "category": "Psychology",
        "topic": "A silent 1918 film trick proves your brain hallucinates emotion from context",
        "style": "inside-out",
        "evidence_type": "scientific_study",
        "discovery_origin": "archived_research",
        "archived_reason": "Psychology trivia replaced by documentary focus.",
        "sources": [
            "https://en.wikipedia.org/wiki/Kuleshov_effect",
        ],
        "claims": [
            "Lev Kuleshov intercut a neutral expression with soup, a coffin, and a child, evoking different perceived emotions.",
        ],
    },
]
