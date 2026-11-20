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
    print(f'TEST: {t}')
    for i in range(len(lines)):
        l = lines[i]
        speed = l.get('speed', 1.0)
        mode = l.get('delivery_mode', 'default')
        if i < len(lines) - 1:
            gap = lines[i+1]['start'] - l['end']
            print(f"  Line {i+1} -> Line {i+2} [{mode:11s} (speed {speed:.2f}x)] | Spoken: {l['end']-l['start']:5.2f}s | Gap to next: {gap:5.3f}s")
        else:
            trailing = data.get('duration', 0.0) - l['end']
            print(f"  Line {i+1} [FINAL: {mode:7s} (speed {speed:.2f}x)] | Spoken: {l['end']-l['start']:5.2f}s | Trailing silence: {trailing:5.3f}s")
