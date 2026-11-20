import json
import os
import subprocess

tests = [
    'test_01_mystery_flight19',
    'test_02_history_monalisa',
    'test_03_space_shoemakerlevy',
    'test_04_creator_horror_ep1'
]

os.makedirs('output/incident_eval/audit_frames', exist_ok=True)

for t in tests:
    base = f'output/incident_eval/{t}'
    mp4 = f'output/incident_eval/{t}.mp4'
    with open(f'{base}/data/lines.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    lines = data.get('lines', [])
    for l in lines:
        mid = (l['start'] + l['end']) / 2.0
        idx = l['i'] + 1
        out_jpg = f'output/incident_eval/audit_frames/{t}_line{idx:02d}_t{int(mid):02d}s.jpg'
        cmd = [
            'ffmpeg', '-y', '-ss', f'{mid:.2f}', '-i', mp4,
            '-vframes', '1', '-q:v', '2', out_jpg
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f'Extracted {out_jpg} at {mid:.2f}s for Line {idx}')
