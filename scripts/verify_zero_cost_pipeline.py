import os
import sys
import json
import time

sys.path.insert(0, os.path.abspath("."))

# Strictly clear any Gemini API key to prove ₹0 operation
os.environ["GEMINI_API_KEY"] = ""

from curiosity_engine.intelligence.local_model import local_model
from curiosity_engine.content.editorial_policy import validate_editorial_category

print("=" * 60)
print("ZERO-COST LOCAL-FIRST VERIFICATION TEST")
print("=" * 60)
print(f"Ollama local model available: {local_model.is_available()}")
assert local_model.is_available(), "Local model must be reachable on localhost:11434"

# 1. Test topic validation
test_topics = [
    ("The Ghost Blimp of 1942: L-8 Returns with No Crew", "MYSTERY"),
    ("The Voynich Manuscript: Cryptic Parchment No Botanist Can Decode", "HISTORY"),
    ("The 1977 Wow! Signal: 72 Seconds of Deep Space Telemetry", "SPACE"),
]

for title, cat in test_topics:
    is_valid, resolved_cat, reason = validate_editorial_category(title, declared_category=cat)
    print(f"Category Check: [{cat}] '{title[:45]}...' -> Valid={is_valid}, Cat={resolved_cat}")
    assert is_valid, f"Expected valid category for {title}"

print("\n[SUCCESS] Editorial Policy correctly verified 3 strict pillars at ₹0 cost.")
