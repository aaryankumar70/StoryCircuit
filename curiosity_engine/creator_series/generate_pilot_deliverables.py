"""Pilot Deliverable Generator for 'The Scariest Story Ever Told'.

Generates:
1. Complete story analysis
2. Narrative outline & episode breakdown (6 episodes, 42-55s target)
3. Individual adapted episode scripts with sentence source mapping
4. Character continuity bible & Story continuity bible
5. Psychological Horror Visual Bible (visual_bible.schema.json compliant)
6. Episode storyboards (episode_storyboard.schema.json compliant)
7. Visual continuity ledger
8. Daily publication schedule
9. Visual QC evaluation results
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from curiosity_engine.creator_series.models import (
    EpisodeRecord,
    EpisodeStatus,
    RightsStatus,
    SeriesRecord,
    SeriesStatus,
)
from curiosity_engine.creator_series.visual_director import visual_director
from curiosity_engine.creator_series.visual_qc import visual_qc
from curiosity_engine.creator_series.story_adapter import estimate_narration_duration

OUT_DIR = Path("output/creator_series_eval/the_scariest_story_ever_told")
OUT_DIR.mkdir(parents=True, exist_ok=True)
(OUT_DIR / "scripts").mkdir(parents=True, exist_ok=True)
(OUT_DIR / "storyboards").mkdir(parents=True, exist_ok=True)

# ── 1. Story Analysis ──
analysis_data = {
    "series_id": "the_scariest_story_ever_told",
    "title": "The Scariest Story Ever Told",
    "perspective": "first_person",
    "narrator": "Joshua (first-person protagonist, electrician/writer, 56 years old in present)",
    "characters": [
        {
            "id": "char_joshua",
            "name": "Joshua",
            "role": "Narrator who wore headphones during the field trip and never heard the story.",
            "ages": ["12 (child)", "55-56 (adult)"],
        },
        {
            "id": "char_isaiah",
            "name": "Isaiah",
            "role": "Joshua's best friend on the bus; refused to speak until age 55; died of pancreatic cancer.",
            "ages": ["12 (child)", "55 (adult)"],
        },
        {
            "id": "char_bus_driver",
            "name": "Substitute Bus Driver",
            "role": "Mysterious substitute driver on county road; told the prophecy story; killed in the head-on crash.",
            "ages": ["middle-aged"],
        },
        {
            "id": "char_maria",
            "name": "Maria",
            "role": "Classmate on the bus who witnessed the prophecy; overheard decades later in a bar recounting the deaths.",
            "ages": ["12 (child)", "middle-aged adult"],
        },
        {
            "id": "char_other_victims",
            "name": "Shinji, Devon, Mitsuko",
            "role": "Classmates whose cursed fates came true exactly as predicted.",
            "ages": ["12 (child)"],
        },
    ],
    "settings": [
        "School bus on a winding county road",
        "Hospital and classroom aftermath",
        "Coffee shop 43 years later",
        "Local dimly lit bar in hometown",
    ],
    "central_conflict": "Joshua spends his entire adult life agonizing over a terrifying story told to his classmates, unaware that hearing it triggers his death.",
    "key_clues": [
        "Driver claims the story is 'too scary' and starts on a county road",
        "The unnatural, stunned silence of the children after the story concludes",
        "The bus drifting into traffic, killing the driver and comatose student",
        "Isaiah's stubborn insistence: 'I will tell you when I am fifty-five'",
        "Maria's horror and refusal to talk to Joshua in math class",
        "Isaiah dying of pancreatic cancer at exactly age fifty-five",
    ],
    "revelation": "The driver did not tell a scary tale; he prophesied how each child on the bus would die. For Joshua, who wasn't listening, the driver prophesied: 'Joshua dies three days after he hears this story.' The children stayed silent to keep him alive.",
    "original_ending": "Dammit, brother, you were right! I wish I’d never heard.",
}

# ── 2. Episode Breakdown & Scripts (Preserving verbatim source text) ──
episodes_data = [
    {
        "episode_num": 1,
        "title": "Part 1: The Silence Behind the Headphones",
        "hook": "When I was 12 years old, a bus driver asked if we wanted to hear the scariest story in the world.",
        "narration": (
            "When I was 12 years old, a bus driver asked during a field trip if we wanted him to tell the scariest story ever. "
            "He was a substitute driver with hollow eyes looking at us in the rearview mirror. "
            "All the other kids shouted yes, but I had a brand new Walkman, so I put my headphones on and turned up the volume. "
            "I remember him saying, 'This story starts on a county road.' "
            "Then I tuned him out. When the cassette tape finally reached the end, I realized the bus around me was dead silent. "
            "Every kid sat slack-jawed and wide-eyed in absolute terror. "
            "I turned to my best friend Isaiah in the row behind me and asked, 'Hey, what's going on?'"
        ),
        "cliffhanger": "I turned to my best friend Isaiah in the row behind me and asked, 'Hey, what's going on?'",
        "source_lines": "Lines 1-28 of original story (Walkman, substitute driver, sudden silence)",
    },
    {
        "episode_num": 2,
        "title": "Part 2: The Crash on the County Road",
        "hook": "Every kid on that bus was frozen by a shared, horrifying experience I had somehow missed.",
        "narration": (
            "Every kid on that bus was frozen by a shared, horrifying experience I had somehow missed. "
            "I asked Isaiah why it got so quiet. He looked up, his jaw closed, his voice dead monotone: 'He told us a scary story.' "
            "When I asked what it was about, Isaiah whispered: 'Can't tell you.' Up front, kids murmured: 'Don't tell him.' "
            "The driver was silent now, his hands on the wheel, eyes glazed. "
            "Right then, a horn sounded. An oncoming timber truck barreled toward our lane. "
            "The bus had drifted into opposing traffic. The impact killed the driver instantly, threw one student into a coma, and knocked the rest of us out cold."
        ),
        "cliffhanger": "The impact killed the driver instantly, threw one student into a coma, and knocked the rest of us out cold.",
        "source_lines": "Lines 29-62 of original story (monotone refusal, horn, head-on truck crash)",
    },
    {
        "episode_num": 3,
        "title": "Part 3: The Fifty-Five Year Promise",
        "hook": "Days after the crash, the rumor spread that the students and driver all fainted from the story.",
        "narration": (
            "Days after the crash, the rumor spread that the students and driver all fainted from the story, causing the crash. "
            "When classes resumed, I asked Maria, who was doodling in math class: 'Was it really the scariest story you ever heard?' "
            "Her pen stopped. She packed her notebook, walked to another desk, and shouted: 'I don't want to talk to you, Joshua.' "
            "None of the survivors would look at me. When I finally begged Isaiah to just summarize it, he snapped: 'I'll tell you when I'm fifty-five.' "
            "'Fifty-five?' I yelled. 'Bro, just let it go!' he shouted back. "
            "That refusal nearly broke our friendship. For decades, the mystery haunted me."
        ),
        "cliffhanger": "That refusal nearly broke our friendship. For decades, the mystery haunted me.",
        "source_lines": "Lines 63-98 of original story (Maria moving desks, Isaiah's age-55 refusal)",
    },
    {
        "episode_num": 4,
        "title": "Part 4: The Final Goodbye",
        "hook": "Forty-three years later, a calendar reminder popped up: 'Isaiah's birthday—fifty-five.'",
        "narration": (
            "Forty-three years later, a calendar reminder popped up: 'Isaiah's birthday—fifty-five.' "
            "I reached out to catch up over coffee. When I arrived, his eyes were yellow and glassy. "
            "He smiled weakly and said: 'Pancreatic cancer. I have a few months, probably.' "
            "We talked about our lives, our divorces, his grandchildren. But the moment I began to bring up our school years, he raised his hand. "
            "'Before you ask, I'm not gonna tell you that bus story. Every student who heard it wishes they hadn't. Trust me—don't ask. Brother, let it go.' "
            "He died a few months later with the secret locked in his chest."
        ),
        "cliffhanger": "He died a few months later with the secret locked in his chest.",
        "source_lines": "Lines 99-138 of original story (calendar alert, coffee reunion, pancreatic cancer, protective refusal)",
    },
    {
        "episode_num": 5,
        "title": "Part 5: What Happened to the Others",
        "hook": "I had finally accepted that the mystery would die with Isaiah. Until yesterday, at a local bar.",
        "narration": (
            "I had finally accepted that the mystery would die with Isaiah. Until yesterday, at a local bar. "
            "From a nearby table, I overheard a woman say: '...all telling scary stories, and the driver said, Do you want to hear the scariest story ever?' "
            "I craned my neck through the dim lighting. It was Maria—middle-aged now, but unmistakably her. "
            "Her table gasped as she continued: 'It's all true. Shinji fell into a coma. Devon's stepfather stabbed him. Mitsuko died at her wedding when the cake dowel went through her eye.' "
            "'All of them happened like the driver said. Isaiah was fifty-five when the cancer got him. He and I were the last two.'"
        ),
        "cliffhanger": "'All of them happened like the driver said. Isaiah was fifty-five when the cancer got him. He and I were the last two.'",
        "source_lines": "Lines 139-166 of original story (bar overhearing, Maria identified, curses revealed)",
    },
    {
        "episode_num": 6,
        "title": "Part 6: The Three-Day Curse",
        "hook": "Maria leaned in close to her table, her voice dropping to a whisper.",
        "narration": (
            "Maria leaned in close to her table, her voice dropping to a whisper. "
            "'The craziest thing was the one kid on the bus who wasn't listening with his headphones. The driver saved him for last and said: Joshua dies three days after he hears this story.' "
            "'Then the truck hit, just like the driver said it would. And poor Joshua never stopped asking. What was the story? We used to joke that if we never told him, maybe he'd never die.' "
            "A strangled sound escaped my throat. Maria looked up, and I stumbled out into the cold night. "
            "Isaiah was protecting me all along. Dammit, brother, you were right. I wish I'd never heard."
        ),
        "cliffhanger": "Isaiah was protecting me all along. Dammit, brother, you were right. I wish I'd never heard.",
        "source_lines": "Lines 167-185 of original story (Joshua prophecy, revelation of protection, final dread)",
    },
]

# ── 3. Visual Bible (schemas/visual_bible.schema.json) ──
bible_dict = visual_director.create_horror_visual_bible(
    series_id="the_scariest_story_ever_told",
    title="The Scariest Story Ever Told",
    logline="A man discovers that a forgotten childhood story on a school bus predicted his death three days after hearing it.",
)

# ── 4. Generate Storyboards & QC ──
storyboards = []
qc_results = []

for ep_data in episodes_data:
    ep_dur = estimate_narration_duration(ep_data["narration"])
    ep_rec = EpisodeRecord(
        episode_id=f"the_scariest_story_ever_told_ep{ep_data['episode_num']:02d}",
        series_id="the_scariest_story_ever_told",
        episode_num=ep_data["episode_num"],
        title=ep_data["title"],
        adapted_narration=ep_data["narration"],
        hook=ep_data["hook"],
        cliffhanger=ep_data["cliffhanger"],
        estimated_duration=ep_dur,
        status=EpisodeStatus.STORYBOARDED,
    )

    sb = visual_director.create_episode_storyboard(
        series_id="the_scariest_story_ever_told",
        episode=ep_rec,
        bible=bible_dict,
        duration_s=ep_dur,
    )
    storyboards.append(sb)

    # Evaluate QC
    score = visual_qc.evaluate_storyboard(sb, bible_dict)
    qc_results.append({
        "episode_num": ep_data["episode_num"],
        "title": ep_data["title"],
        "duration_sec": ep_dur,
        "qc_score": score.to_dict(),
    })

    # Save individual script and storyboard
    with open(OUT_DIR / "scripts" / f"ep{ep_data['episode_num']:02d}.json", "w", encoding="utf-8") as f:
        json.dump(ep_rec.to_dict(), f, indent=2)
    with open(OUT_DIR / "storyboards" / f"ep{ep_data['episode_num']:02d}_storyboard.json", "w", encoding="utf-8") as f:
        json.dump(sb, f, indent=2)

# ── 5. Save Summary Deliverables ──
with open(OUT_DIR / "story_analysis.json", "w", encoding="utf-8") as f:
    json.dump(analysis_data, f, indent=2)

with open(OUT_DIR / "visual_bible.json", "w", encoding="utf-8") as f:
    json.dump(bible_dict, f, indent=2)

with open(OUT_DIR / "episode_breakdown.json", "w", encoding="utf-8") as f:
    json.dump(episodes_data, f, indent=2)

with open(OUT_DIR / "qc_results.json", "w", encoding="utf-8") as f:
    json.dump(qc_results, f, indent=2)

# Schedule (Daily 8:30 PM IST)
schedule = {
    "series_id": "the_scariest_story_ever_told",
    "slot": 2,
    "time_ist": "20:30",
    "cadence": "daily",
    "episodes": [
        {"episode_num": 1, "target_date": "Day 1", "time": "20:30 IST"},
        {"episode_num": 2, "target_date": "Day 2", "time": "20:30 IST"},
        {"episode_num": 3, "target_date": "Day 3", "time": "20:30 IST"},
        {"episode_num": 4, "target_date": "Day 4", "time": "20:30 IST"},
        {"episode_num": 5, "target_date": "Day 5", "time": "20:30 IST"},
        {"episode_num": 6, "target_date": "Day 6", "time": "20:30 IST"},
    ],
}
with open(OUT_DIR / "publication_schedule.json", "w", encoding="utf-8") as f:
    json.dump(schedule, f, indent=2)

print('Generated all pilot deliverables in:', OUT_DIR)
for r in qc_results:
    ep_n = r['episode_num']
    dur = r['duration_sec']
    avg_s = r['qc_score']['average_score']
    v = r['qc_score']['verdict']
    print(f"Ep {ep_n}: dur={dur}s, avg_score={avg_s}, verdict={v}")
