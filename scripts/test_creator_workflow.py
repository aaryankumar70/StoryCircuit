"""Opt-in live smoke test for a manually running Creator Studio server.

This file is intentionally inert during pytest collection. Running it against a
live server can create and edit persistent Creator Studio data.
"""
import argparse
import json
import os
import urllib.request

TEST_STORY = """The night watchman at Blackwood Forest had one single rule: never answer the telephone in cabin four. For thirty-five years, that cabin stood boarded up with iron chains. But on a freezing Tuesday in November, the vintage copper bell began to ring. Officer Miller approached the rusted door with his flashlight trembling in his grip. As he pried the latch open, the ringing stopped abruptly. Inside, on a dust-covered wooden desk, sat a handwritten log with today's date and his own name written in fresh black ink. Beside the journal lay a brass key he had lost twelve years ago in the river."""

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true", help="Allow mutations against the running local Creator Studio API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Local dashboard/API base URL")
    args = parser.parse_args()
    if not args.allow_live or os.environ.get("CURIOLOOP_ALLOW_LIVE_SMOKE") != "YES":
        parser.error("Live smoke test requires both --allow-live and CURIOLOOP_ALLOW_LIVE_SMOKE=YES; use mocked tests for routine verification.")
    if not args.base_url.startswith("http://127.0.0.1:") and not args.base_url.startswith("http://localhost:"):
        parser.error("This smoke test only supports a loopback local server.")

    payload = json.dumps({
        'title': 'The Cabin Four Mystery', 'raw_text': TEST_STORY, 'duration_preset': '1m',
        'author': 'Detective Miller', 'permission_status': 'VERIFIED'
    }).encode('utf-8')
    req = urllib.request.Request(args.base_url.rstrip('/') + '/api/series/breakdown', data=payload,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=20) as response:
        res = json.loads(response.read())
    series_id = res['series']['series_id']
    print('Created series:', series_id, 'Episodes:', len(res['episodes']))

    ep = res['episodes'][0]
    print('Ep 1 Initial Status:', ep['status'])
    print('Ep 1 Hook:', ep['hook'])

    edit_payload = json.dumps({
        'episode_id': ep['episode_id'],
        'adapted_narration': 'The night watchman had one single rule. Never answer cabin four.'
    }).encode('utf-8')
    req2 = urllib.request.Request(args.base_url.rstrip('/') + f'/api/series/{series_id}/episodes/edit', data=edit_payload,
                                  headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req2, timeout=20) as response:
        res2 = json.loads(response.read())
    print('Ep 1 Status After Edit:', res2['episode']['status'])
    assert res2['episode']['status'] == 'STALE_INVALIDATED', f"Expected STALE_INVALIDATED, got {res2['episode']['status']}"
    print('[SUCCESS] Creator Studio story ingestion, segmentation, and cascading invalidation verified!')

if __name__ == "__main__":
    main()
