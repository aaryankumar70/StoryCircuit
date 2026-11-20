import json
from pathlib import Path

base_dir = Path("output/incident_eval")
test_ids = [
    "test_01_mystery_flight19",
    "test_02_history_monalisa",
    "test_03_space_shoemakerlevy",
    "test_04_creator_horror_ep1"
]
summary = []
for tid in test_ids:
    f = base_dir / f"{tid}_result.json"
    if f.exists():
        summary.append(json.loads(f.read_text(encoding="utf-8")))

summary_file = base_dir / "incident_verification_summary.json"
summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(f"Wrote {len(summary)} results to {summary_file}")
for s in summary:
    qc_str = "PASSED" if s["qc_passed"] else "FAILED"
    size = Path(s["video_mp4"]).stat().st_size
    print(f"- {s['test_id']}: QC={qc_str}, Score={s['overall_score']}, Dur={s['duration_sec']}s, MP4 Size={size:,} bytes")
