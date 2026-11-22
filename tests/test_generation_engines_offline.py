"""Offline contract tests for the new generation engines and their data guards."""
from __future__ import annotations

import copy
import importlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from curiosity_engine.creator_series.creator_studio_engine import CreatorStudioEngine
from curiosity_engine.generation.cartoon_visual_engine import Cartoon3DVisualEngine, _script_for_visuals
from curiosity_engine.creator_series.production_planner import ProductionPlanner
from curiosity_engine.generation.contracts import GenerationEngineError, UnconfiguredScriptEngine
from curiosity_engine.generation.engine_registry import engine_registry
from curiosity_engine.generation.ollama_script_engine import OllamaScriptEngine, ScriptDraft
from curiosity_engine.intelligence.local_model import LocalModelAdapter, LocalModelError
from curiosity_engine.production.asset_system import build_asset_manifest
from curiosity_engine.production.renderer import render_project_video
from curiosity_engine.production.visual_director import assign_narrative_scenes
from curiosity_engine.production.visual_style_selector import select_visual_style

local_model_module = importlib.import_module("curiosity_engine.intelligence.local_model")


HOOK = "One tiny signal sent this mystery in a completely different direction."
HOOKS = [HOOK, "The clue everyone ignored was hiding in plain sight.",
         "At first the evidence appeared to tell one simple story.",
         "A small detail changed what investigators thought they knew.",
         "The last recorded entry raised a question no one could answer."]
LINES = [
    (HOOK, "A witness notices the signal before anyone understands its meaning.", "dim archive room", ["watchman"], ["signal lamp"]),
    ("The first report described a routine event with no unusual warning.", "Investigators compare the first report with the original record.", "records office", ["archivist"], ["ledger"]),
    ("Then a second account placed the same event somewhere unexpected.", "Two witnesses point toward different landmarks on a map.", "old town street", ["witnesses"], ["map"]),
    ("A surviving note showed that one important detail was missing.", "An archivist turns a page and finds a handwritten annotation.", "records office", ["archivist"], ["notebook"]),
    ("That detail narrowed the timeline but did not settle the cause.", "A clock and two dated records frame the unresolved timeline.", "archive table", ["investigator"], ["clock", "documents"]),
    ("The evidence now supports a careful answer, with one question remaining.", "The investigator closes the file while the final question stays open.", "archive room", ["investigator"], ["case file"]),
]


def draft_data(lines=LINES, hook=HOOK):
    return {
        "title_candidates": ["The Signal in the Record", "A Clue in the Archive"],
        "hook_alternatives": HOOKS, "selected_hook": hook,
        "beats": ["The report", "A contradiction", "The missing note", "What remains unknown"],
        "lines": [{"scene_id": f"scene_{i + 1:02d}", "narration": row[0], "visual_description": row[1],
                   "visual_cues": [row[1]], "characters": row[3], "environment": row[2], "props": row[4],
                   "camera": "medium shot, slow push in", "lighting": "warm archive light",
                   "animation": "the investigator turns the page and reacts to the clue", "transition": "cut",
                   "continuity": "Keep the same investigator, coat, and room palette",
                   "estimated_start_sec": 0, "estimated_end_sec": 0}
                  for i, row in enumerate(lines)],
        "factual_claims": [{"claim": "The supplied test source contains a dated report.",
                            "source_refs": ["official_record"], "certainty": "supported"}],
        "source_refs": ["official_record"], "uncertainty_warnings": ["The cause remains unresolved."],
        "estimated_duration": 30.0,
    }


class FakeAdapter:
    def __init__(self, result=None):
        self.model_name = ""
        self.result = result or draft_data()
        self.calls = []

    def is_available(self):
        return True

    def generate_structured(self, prompt, schema, **kwargs):
        self.calls.append((prompt, schema, kwargs))
        value = self.result.pop(0) if isinstance(self.result, list) else self.result
        return schema.model_validate(copy.deepcopy(value))


@pytest.fixture(autouse=True)
def personal_eval_gate(monkeypatch):
    monkeypatch.setenv("CURIOLOOP_ENGINE_ACTIVATION", "personal_non_commercial_experimentation")
    monkeypatch.setenv("CURIOLOOP_ACK_QWEN_RESEARCH_LICENSE", "YES")


def test_qwen_license_gate_fails_closed_without_ack(monkeypatch):
    adapter = FakeAdapter()
    engine = OllamaScriptEngine(adapter=adapter, model_name="qwen2.5:3b")
    monkeypatch.delenv("CURIOLOOP_ACK_QWEN_RESEARCH_LICENSE")
    assert not engine.is_configured()
    assert "research license" in engine.not_configured_reason().lower()
    assert adapter.calls == []


def test_creator_story_enrichment_respects_shared_engine_gate(monkeypatch):
    class DirectAdapter:
        def __init__(self):
            self.calls = 0

        def generate_json(self, **kwargs):
            self.calls += 1
            return {"subject": "Model enrichment", "primary_genre": "Mystery"}

    adapter = DirectAdapter()

    class UnconfiguredButHasAdapter(UnconfiguredScriptEngine):
        def __init__(self):
            self.adapter = adapter

    monkeypatch.setattr(engine_registry, "_script_engine", UnconfiguredButHasAdapter())
    result = CreatorStudioEngine.analyze_story("A traveler finds a sealed letter and follows its clues.")
    assert result["subject"]
    assert adapter.calls == 0


def test_creator_story_enrichment_reuses_registered_adapter(monkeypatch):
    class DirectAdapter:
        def __init__(self):
            self.calls = 0

        def generate_json(self, **kwargs):
            self.calls += 1
            return {"subject": "A sealed letter changes the journey.", "primary_genre": "Mystery"}

    adapter = DirectAdapter()

    class ConfiguredScriptEngine:
        def is_configured(self):
            return True

        def __init__(self):
            self.adapter = adapter

    monkeypatch.setattr(engine_registry, "_script_engine", ConfiguredScriptEngine())
    result = CreatorStudioEngine.analyze_story("A traveler finds a sealed letter and follows its clues.")
    assert result["subject"] == "A sealed letter changes the journey."
    assert adapter.calls == 1


def test_structured_script_preserves_evidence_and_narrative_visuals():
    adapter = FakeAdapter()
    engine = OllamaScriptEngine(adapter=adapter)
    result = engine.generate_script({
        "topic": "A Dated Signal in an Archive", "category": "Mysteries", "target_duration": 30,
        "sources": [{"id": "official_record", "title": "Official archive entry", "url": "https://example.test/record"}],
        "claims": ["The report was dated in the archive."],
        "research_dossier": {"central_question": "Why did the two reports differ?",
                             "verified_claims": [{"statement": "The archive has a dated report.",
                                                   "source": "https://example.test/record"}],
                             "uncertainties": ["The cause is unknown."]},
    })
    assert result["word_count"] >= 48
    assert result["lines"][0]["scene"]["visual_description"]
    assert result["lines"][0]["scene"]["estimated_end_sec"] > result["lines"][0]["scene"]["estimated_start_sec"]
    assert result["claims"][0]["source_refs"] == ["official_record"]
    assert result["sources"][0]["id"] == "official_record"
    assert result["research_dossier"]["central_question"] == "Why did the two reports differ?"
    assert result["research_input_claims"][0]["source_refs"] == []
    assert "not a scientifically validated prediction" in result["critic_evaluation"]["note"].lower()
    assert adapter.calls[0][2]["max_tokens"] == 1800


def test_short_first_draft_is_revised_before_final_word_count_validation():
    short_lines = [
        LINES[0],
        ("Mara checks the sealed archive.", "Mara checks the sealed archive door.", "archive room", ["archivist"], ["door"]),
        ("No receiver appears.", "An empty receiver shelf in the archive.", "archive room", ["archivist"], ["shelf"]),
        ("The blinking follows the ledger.", "A blue monitor blinks beside an open ledger.", "archive table", ["archivist"], ["ledger"]),
        LINES[-1],
    ]
    revised_lines = [
        LINES[0],
        ("Mara checks the sealed archive and finds no receiver.", "Mara checks the sealed archive door and an empty shelf.", "archive room", ["archivist"], ["shelf"]),
        ("The monitor blinks only when she opens the old ledger.", "A blue monitor pulses as Mara opens the old ledger.", "archive table", ["archivist"], ["ledger"]),
        ("A final page carries tomorrow's date in her handwriting.", "Mara discovers tomorrow's date written on the final page.", "archive table", ["archivist"], ["page"]),
        LINES[-1],
    ]
    adapter = FakeAdapter([draft_data(short_lines), draft_data(revised_lines)])
    result = OllamaScriptEngine(adapter=adapter).generate_script({
        "topic": "A Dated Signal in an Archive", "category": "Mysteries", "target_duration": 25,
        "sources": [{"id": "official_record", "title": "Official archive entry"}],
        "research_dossier": {"central_question": "Why did the archive signal change?"},
    })
    assert len(adapter.calls) == 2
    assert 48 <= result["word_count"] <= 148
    assert result["lines"][0]["text"] == HOOK
    assert result["lines"][-1]["text"] == LINES[-1][0]
    assert abs(result["duration"] - 25) <= 3


def test_script_engine_rejects_unrelated_narration():
    engine = OllamaScriptEngine(adapter=FakeAdapter())
    with pytest.raises(GenerationEngineError, match="did not retain a central topic"):
        engine.generate_script({"topic": "A Desert Robot", "category": "Fiction",
                                "sources": [{"id": "official_record", "title": "Official record"}],
                                "research_dossier": {}})


def test_compact_narration_output_gets_complete_scenes_offline():
    compact = draft_data()
    compact["lines"] = [row[0] if index % 2 == 0 else {"text": row[0]} for index, row in enumerate(LINES)]
    compact["selected_hook"] = HOOKS[1]
    adapter = FakeAdapter(compact)
    result = OllamaScriptEngine(adapter=adapter).generate_script({
        "topic": "A Dated Signal in an Archive", "category": "Mysteries", "target_duration": 30,
        "sources": [{"id": "official_record", "title": "Official archive entry"}],
        "research_dossier": {"central_question": "Why did the archive signal change?"},
    })
    assert adapter.calls[0][1].__name__ == "ScriptNarrativeDraft"
    assert result["selected_hook"] == result["lines"][0]["text"]
    assert result["selected_hook"] in result["hook_alternatives"]
    assert len(result["lines"]) == 6
    for line in result["lines"]:
        scene = line["scene"]
        assert scene["scene_id"] and scene["environment"] and scene["visual_description"]
        assert scene["camera"] and scene["lighting"] and scene["animation"] and scene["continuity"]


def test_visual_director_assigns_story_specific_scenes_offline():
    source = {"topic": "A Missing Signal", "category": "Mysteries", "lines": [
        {"text": "An archivist finds a signal scratched into the lighthouse log."},
        {"text": "A sailor follows the fading light toward the empty harbor."},
    ]}
    directed = assign_narrative_scenes(source)
    first, second = [line["scene"] for line in directed["lines"]]
    assert "signal" in first["visual_description"].lower()
    assert first["environment"] != second["environment"] or first["props"] != second["props"]
    assert first["characters"] and "Archivist" in first["characters"]
    assert first["estimated_end_sec"] <= second["estimated_start_sec"]
    assert first["camera"] != second["camera"]
    assert "scene" not in source["lines"][0]


def test_creator_storyboard_is_narration_led_and_adapts_nested_fields():
    narration = (
        "An archivist opens the sealed logbook in the reading room. "
        "A final entry describes the arrival that has not happened yet."
    )
    storyboard = ProductionPlanner().generate_threejs_storyboard(
        "test-series", 1, "The Unwritten Arrival", narration, "psychological_horror", 8.0
    )
    scenes = storyboard["scenes"]
    assert scenes
    assert all(scene["narration"]["text"] in scene["visual_objective"] for scene in scenes)
    assert all(scene["three_js_scene"].startswith("cartoon3d_") for scene in scenes)
    assert all(scene["rendering_method"] == "CARTOON_3D_THREEJS" for scene in scenes)
    assert not any("Atlantic" in scene["environment"]["name"] for scene in scenes)

    adapted = _script_for_visuals({
        "title": "The Unwritten Arrival",
        "episode": {"title": "Episode 1", "estimated_duration": 8.0, "storyboard": storyboard},
    })
    assert [line["text"] for line in adapted["lines"]] == [scene["narration"]["text"] for scene in scenes]
    assert all("{'text':" not in line["text"] for line in adapted["lines"])


def test_script_validation_rejects_unknown_source_refs():
    invalid = draft_data()
    invalid["factual_claims"][0]["source_refs"] = ["invented_source"]
    engine = OllamaScriptEngine(adapter=FakeAdapter(invalid))
    with pytest.raises(GenerationEngineError, match="unknown evidence IDs"):
        engine.generate_script({"topic": "Archive", "category": "Mysteries",
                                "sources": [{"id": "official_record", "title": "Official record"}],
                                "research_dossier": {}})
    # The model is never allowed to turn an unknown reference into provenance.


def test_local_adapter_retries_malformed_json_with_a_hard_bound(monkeypatch):
    adapter = LocalModelAdapter()
    responses = [LocalModelError("malformed JSON"), draft_data()]
    monkeypatch.setattr(adapter, "generate_json", lambda **kwargs: (_ for _ in ()).throw(responses.pop(0))
                        if isinstance(responses[0], Exception) else responses.pop(0))
    result = adapter.generate_structured("prompt", ScriptDraft, max_retries=20)
    assert result.selected_hook == HOOK

    calls = []
    monkeypatch.setattr(adapter, "generate_json", lambda **kwargs: (calls.append(kwargs) or {}))
    with pytest.raises(LocalModelError, match="after 4 attempts"):
        adapter.generate_structured("prompt", ScriptDraft, max_retries=99)
    assert len(calls) == 4


def test_local_model_context_is_configurable_and_sent_to_ollama(monkeypatch):
    monkeypatch.setenv("LOCAL_LLM_CONTEXT_SIZE", "8192")
    adapter = LocalModelAdapter()
    posted = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "ok"}

    def fake_post(endpoint, json, timeout):
        posted.update({"endpoint": endpoint, "payload": json, "timeout": timeout})
        return Response()

    monkeypatch.setattr(adapter, "_ensure_ollama_ready", lambda: True)
    monkeypatch.setattr(local_model_module.requests, "post", fake_post)
    assert adapter.generate("short test prompt") == "ok"
    assert posted["payload"]["options"]["num_ctx"] == 8192

    monkeypatch.setenv("LOCAL_LLM_CONTEXT_SIZE", "32768")
    assert LocalModelAdapter().context_size == 32768
    with pytest.raises(ValueError, match="4096 and 32768"):
        LocalModelAdapter(context_size=32769)


def test_schema_rejects_extra_fields_and_bad_scene_timing():
    bad = draft_data()
    bad["unexpected"] = "must not pass through"
    with pytest.raises(ValidationError):
        ScriptDraft.model_validate(bad)
    bad = draft_data()
    bad["lines"][0]["estimated_start_sec"] = 4
    bad["lines"][0]["estimated_end_sec"] = 2
    with pytest.raises(ValidationError):
        ScriptDraft.model_validate(bad)


def test_duration_rewrite_preserves_selected_hook_and_sourced_claims():
    original = draft_data()
    expanded_lines = LINES[:-1] + [
        ("Researchers checked the original documents before drawing any conclusion.", "A researcher compares two source documents side by side.", "archive office", ["researcher"], ["documents"]),
        ("Their records agree about the date but not the explanation.", "Two open records share a date but show different annotations.", "archive table", ["researcher"], ["records"]),
        LINES[-1],
    ]
    expanded = draft_data(expanded_lines)
    adapter = FakeAdapter([draft_data(), expanded])
    engine = OllamaScriptEngine(adapter=adapter)
    script = engine.generate_script({"topic": "An Archive Signal", "category": "Mysteries", "target_duration": 30,
                                     "sources": [{"id": "official_record", "title": "Official archive entry"}],
                                     "research_dossier": {}})
    revised = engine.revise_duration(script, 40)
    assert revised["selected_hook"] == HOOK
    assert revised["claims"] == script["claims"]
    assert 35 <= revised["duration"] <= 45
    assert revised["word_count"] == sum(len(line["text"].split()) for line in revised["lines"])


@pytest.mark.parametrize(("category", "topic", "expected"), [
    ("Mysteries", "A dated archive report", "mystery"),
    ("History", "A vanished expedition", "historical"),
    ("Space", "A signal near Saturn", "space"),
    ("Science", "A laboratory experiment", "science"),
])
def test_visual_style_selector_uses_supported_cartoon_profiles(category, topic, expected):
    assert select_visual_style({"topic": topic, "category": category})["profile"] == expected


def test_asset_catalog_reuses_stable_identity_and_records_license():
    manifest = build_asset_manifest({"topic": "The Archive", "lines": [
        {"text": "One", "scene": {"characters": ["Investigator"], "environment": "Archive", "props": ["Ledger"], "animation": "Turns the page"}},
        {"text": "Two", "scene": {"characters": ["investigator"], "environment": "Archive", "props": ["Ledger"], "animation": "Turns the page"}},
    ]})
    assert len(manifest["characters"]) == 1
    assert manifest["characters"][0]["license"].startswith("CurioLoop original")
    assert len(manifest["props"]) == 1
    assert manifest["renderer_family"] == "cartoon_3d"


def test_project_preparation_is_immutable_and_has_directed_scenes(tmp_path):
    engine = Cartoon3DVisualEngine()
    if not engine.is_configured():
        pytest.skip(engine.not_configured_reason())
    script = {"topic": "An Archive Signal", "category": "Mysteries", "duration": 30,
              "lines": [{"text": row[0], "scene": {"visual_description": row[1], "environment": row[2],
                        "characters": row[3], "props": row[4], "scene_id": f"scene_{i}"}}
                        for i, row in enumerate(LINES)]}
    project = engine.prepare_project("offline_scene", script, tmp_path)
    stored = json.loads((project / "script.json").read_text(encoding="utf-8"))
    marker = json.loads((project / ".curioloop_project.json").read_text(encoding="utf-8"))
    assert marker["project_id"] == project.name
    assert marker["renderer_version"] == "cartoon3d-v2"
    assert stored["asset_manifest"]["characters"]
    assert len(json.loads((project / "storyboard.json").read_text(encoding="utf-8"))["scenes"]) == len(LINES)
    changed = engine.prepare_project("offline_scene", {**script, "title": "Modified"}, tmp_path)
    assert changed != project
    assert json.loads((project / "script.json").read_text(encoding="utf-8"))["topic"] == "An Archive Signal"


def test_cartoon_render_builds_base_mix_before_story_cues(tmp_path, monkeypatch):
    from curiosity_engine.generation import cartoon_visual_engine as renderer

    output_root = tmp_path / "output"
    project = output_root / ".engine_projects" / "render-test" / "script-key"
    (project / "data").mkdir(parents=True)
    (project / "tools").mkdir()
    (project / "tools" / "mix.py").write_text("# mixer stub", encoding="utf-8")
    (project / "tools" / "capture.mjs").write_text("// capture stub", encoding="utf-8")
    (project / ".curioloop_project.json").write_text(json.dumps({"engine": "Cartoon3DVisualEngine"}), encoding="utf-8")
    (project / "script.json").write_text(json.dumps({"lines": [{"text": "A small signal crosses the room."}]}), encoding="utf-8")
    (project / "storyboard.json").write_text(json.dumps({"scenes": []}), encoding="utf-8")
    (project / "data" / "lines.json").write_text(json.dumps({"duration": 25.0, "lines": []}), encoding="utf-8")
    (project / "data" / "narration.wav").write_bytes(b"n" * 12_000)
    tmp_render = tmp_path / "render-temp"
    monkeypatch.setenv("CURIOLOOP_RENDER_TMP_DIR", str(tmp_render))
    monkeypatch.setenv("CURIOLOOP_RENDER_MAX_TMP_GB", "1")
    monkeypatch.setenv("CURIOLOOP_RENDER_MIN_FREE_GB", "0")
    monkeypatch.setenv("CURIOLOOP_RENDER_MIN_OUTPUT_FREE_GB", "0")
    monkeypatch.setenv("CURIOLOOP_RENDER_TIMEOUT_SEC", "60")
    monkeypatch.setenv("CURIOLOOP_RENDER_MAX_DURATION_SEC", "60")

    engine = Cartoon3DVisualEngine()
    monkeypatch.setattr(engine, "is_configured", lambda: True)
    monkeypatch.setattr(renderer, "_synchronize_storyboard_timing", lambda _project: None)
    calls = []

    def fake_capture(cmd, cwd, env, log_path, timeout, label, max_temp_bytes):
        calls.append(label)
        if label in {"base narration sound mix", "procedural sound design mix"}:
            (cwd / "data" / "mix.wav").write_bytes(b"m" * 12_000)
        elif label == "scene and SFX cue capture":
            (cwd / "data" / "cues.json").write_text(json.dumps({"cues": []}), encoding="utf-8")
        elif label == "EBU R128 audio normalization":
            Path(cmd[-1]).write_bytes(b"n" * 12_000)
        elif label == "Chromium/Three.js/FFmpeg video render":
            Path(cmd[-1]).write_bytes(b"v" * 60_000)

    monkeypatch.setattr(Cartoon3DVisualEngine, "_run_capture", staticmethod(fake_capture))
    monkeypatch.setattr(renderer, "validate_rendered_mp4", lambda *_args, **_kwargs: {
        "size_bytes": 60_000, "duration": 25.0, "width": 1080, "height": 1920, "fps": 30.0,
        "video_codec": "h264", "audio_codec": "aac",
    })
    monkeypatch.setattr(renderer, "write_render_manifest", lambda *_args, **_kwargs: None)
    output = output_root / "render-test.mp4"
    rendered = engine.render_video(project, output, resume=False)
    assert rendered == output
    assert calls.index("base narration sound mix") < calls.index("scene and SFX cue capture")
    assert calls.index("scene and SFX cue capture") < calls.index("procedural sound design mix")
    assert calls[-1] == "Chromium/Three.js/FFmpeg video render"


def test_cartoon_environment_selection_matches_archive_story_not_mystery_mood():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required to exercise the Three.js scene selector.")
    shots = Path(__file__).parents[1] / "templates" / "cartoon-3d" / "src" / "environment.js"
    import_stmt = f"import {{ environmentKind }} from {json.dumps(shots.resolve().as_uri())};"
    check = (
        import_stmt +
        "\nconst kind = environmentKind('The Archive Signal at Night with an Open Ledger', 'mystery');"
        + "\nconsole.log(kind);"
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", check],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "archive"


def test_renderer_preserves_unbound_existing_mp4(tmp_path):
    project = tmp_path / ".engine_projects" / "conflict" / "project"
    project.mkdir(parents=True)
    (project / "script.json").write_text("{}", encoding="utf-8")
    (project / ".curioloop_project.json").write_text(json.dumps({
        "project_id": "project", "renderer_version": "cartoon3d-v2",
    }), encoding="utf-8")
    output = tmp_path / "existing.mp4"
    original = b"preserve this unrelated deliverable"
    output.write_bytes(original)
    with pytest.raises(RuntimeError, match="not bound to this project script"):
        render_project_video(project, output)
    assert output.read_bytes() == original
