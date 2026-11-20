import json

tests = [
    'test_01_mystery_flight19',
    'test_02_history_monalisa',
    'test_03_space_shoemakerlevy',
    'test_04_creator_horror_ep1'
]

for t in tests:
    base = f'output/incident_eval/{t}'
    with open(f'{base}/data/lines.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    lines = data.get('lines', [])
    print('========================================================')
    print(f'TEST: {t} | Total Duration: {data.get("duration")}s | Lines: {len(lines)}')
    for l in lines:
        dur = l['end'] - l['start']
        print(f"  Line {l['i']+1} [{l['start']:5.2f}s - {l['end']:5.2f}s | {dur:4.2f}s] Mode: {l.get('delivery_mode', 'default'):11s} (Speed: {l.get('speed', 1.0)}x): \"{l['text']}\"")
