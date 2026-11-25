"""Anti-repeat deduplication for topics and scripts."""
from __future__ import annotations

import re
from typing import Iterable, List, Set, Tuple

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "of", "in", "on", "at", "to", "for",
    "with", "by", "from", "that", "this", "it", "is", "was", "were", "are",
    "be", "been", "how", "why", "what", "when", "where", "who", "you", "your",
    "they", "their", "about", "into", "over", "after", "before", "never", "ever",
})


def normalize_text(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def content_tokens(text: str) -> List[str]:
    return [tok for tok in normalize_text(text).split() if len(tok) > 2 and tok not in _STOPWORDS]


def word_ngrams(tokens: List[str], n: int = 3) -> Set[str]:
    if len(tokens) < n:
        return set(tokens)
    return {" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def jaccard_similarity(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def find_similar_match(
    candidate_title: str,
    candidate_body: str,
    existing_records: Iterable[Tuple[str, str]],
    ngram_threshold: float = 0.30,
    keyword_threshold: float = 0.68,
) -> Tuple[bool, str]:
    """Return (is_duplicate, reason) comparing candidate against (title, body) history."""
    norm_title = normalize_text(candidate_title)
    cand_title_tokens = set(content_tokens(candidate_title))
    cand_body_ngrams = word_ngrams(content_tokens(f"{candidate_title} {candidate_body}"), 3)

    for prev_title, prev_body in existing_records:
        prev_norm = normalize_text(prev_title)
        if norm_title and prev_norm and norm_title == prev_norm:
            return True, f"Exact title match with '{prev_title}'"

        prev_title_tokens = set(content_tokens(prev_title))
        if cand_title_tokens and prev_title_tokens:
            title_overlap = jaccard_similarity(cand_title_tokens, prev_title_tokens)
            if title_overlap >= keyword_threshold:
                return True, f"High title keyword overlap ({title_overlap:.2f}) with '{prev_title}'"

        prev_ngrams = word_ngrams(content_tokens(f"{prev_title} {prev_body}"), 3)
        body_sim = jaccard_similarity(cand_body_ngrams, prev_ngrams)
        if body_sim >= ngram_threshold:
            return True, f"High narrative similarity ({body_sim:.2f}) with '{prev_title}'"

    return False, ""
