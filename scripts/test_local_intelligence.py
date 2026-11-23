import sys, os
sys.path.insert(0, os.path.abspath("."))
from curiosity_engine.intelligence.local_model import local_model
import json
import time

def main():
    print("[1] Testing local_model availability:", local_model.is_available())
    if not local_model.is_available():
        print("Local model engine offline / unconfigured.")
        return
    t0 = time.time()
    prompt = """
Return a JSON object with a 'candidates' list containing 2 historical mystery topics.
Format:
{
  "candidates": [
    {
      "title": "Topic title",
      "category": "MYSTERY",
      "hook": "Opening hook line under 15 words",
      "summary": "2 sentence summary"
    }
  ]
}
"""
    result = local_model.generate_json(prompt, system_instruction="You are a professional historical mystery researcher for CurioLoop. Output strictly valid JSON.")
    dt = time.time() - t0
    print(f"[2] Generated in {dt:.2f}s:")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()

