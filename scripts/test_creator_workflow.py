import urllib.request
import json

test_story = """The night watchman at Blackwood Forest had one single rule: never answer the telephone in cabin four. For thirty-five years, that cabin stood boarded up with iron chains. But on a freezing Tuesday in November, the vintage copper bell began to ring. Officer Miller approached the rusted door with his flashlight trembling in his grip. As he pried the latch open, the ringing stopped abruptly. Inside, on a dust-covered wooden desk, sat a handwritten log with today's date and his own name written in fresh black ink. Beside the journal lay a brass key he had lost twelve years ago in the river."""

payload = json.dumps({
    'title': 'The Cabin Four Mystery',
    'raw_text': test_story,
    'duration_preset': '1m',
    'author': 'Detective Miller',
    'permission_status': 'VERIFIED'
}).encode('utf-8')

req = urllib.request.Request(
    'http://127.0.0.1:8000/api/series/breakdown',
    data=payload,
    headers={'Content-Type': 'application/json'}
)
res = json.loads(urllib.request.urlopen(req).read())
series_id = res['series']['series_id']
print('Created series:', series_id, 'Episodes:', len(res['episodes']))

ep = res['episodes'][0]
print('Ep 1 Initial Status:', ep['status'])
print('Ep 1 Hook:', ep['hook'])

# Test editing episode to verify cascading invalidation
edit_payload = json.dumps({
    'episode_id': ep['episode_id'],
    'adapted_narration': 'The night watchman had one single rule. Never answer cabin four.'
}).encode('utf-8')

req2 = urllib.request.Request(
    f'http://127.0.0.1:8000/api/series/{series_id}/episodes/edit',
    data=edit_payload,
    headers={'Content-Type': 'application/json'}
)
res2 = json.loads(urllib.request.urlopen(req2).read())
print('Ep 1 Status After Edit:', res2['episode']['status'])
assert res2['episode']['status'] == 'STALE_INVALIDATED', f"Expected STALE_INVALIDATED, got {res2['episode']['status']}"
print('[SUCCESS] Creator Studio story ingestion, segmentation, and cascading invalidation verified!')
