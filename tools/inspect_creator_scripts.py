import json

for ep in range(1, 7):
    path = f'output/creator_series_eval/the_scariest_story_ever_told/scripts/ep0{ep}.json'
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f'========================================================')
    print(f'EPISODE {ep}: {data.get("title")}')
    print(f'Narration:\n{data.get("adapted_narration")}')
    print(f'Est. Duration: {data.get("estimated_duration")}s')
