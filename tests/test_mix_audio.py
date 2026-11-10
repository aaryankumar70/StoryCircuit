"""Tests for procedural audio mix engine hardening across all style templates.
Verifies safety against negative, zero, very small, missing, and invalid duration inputs.
"""
from pathlib import Path
import numpy as np
import pytest

TEMPLATES = [
    Path("templates/inside-out/tools/mix.py"),
    Path("templates/paper-atlas/tools/mix.py"),
    Path("templates/stick-story/tools/mix.py"),
]


def load_mix_module(mix_path: Path):
    """Dynamically load and extract mix.py function definitions without triggering script-level file I/O."""
    with open(mix_path, "r", encoding="utf-8") as f:
        code = f.read()

    # Isolate definitions between def safe_dur and music_bed
    start_idx = code.find("def safe_dur")
    end_idx = code.find("# ---------- the music bed")
    assert start_idx != -1, f"def safe_dur not found in {mix_path}"
    assert end_idx != -1, f"music bed section not found in {mix_path}"

    target_code = code[start_idx:end_idx]

    exec_scope = {
        "np": np,
        "signal": pytest.importorskip("scipy.signal"),
        "SR": 48000,
        "rng": np.random.default_rng(42),
    }

    exec(target_code, exec_scope)
    return exec_scope


@pytest.mark.parametrize("template_path", TEMPLATES)
class TestProceduralAudioHardening:

    def test_noise_durations(self, template_path):
        scope = load_mix_module(template_path)
        noise = scope["noise"]

        invalid_durations = [-2.5, -0.01, 0.0, 1e-6, None, "bad_input", float("nan"), float("inf")]
        for d in invalid_durations:
            res = noise(d)
            assert isinstance(res, np.ndarray), f"Failed for {d} in {template_path}"
            assert len(res) >= 1
            assert np.all(np.isfinite(res))

        # Normal positive
        normal = noise(0.2)
        assert len(normal) == int(0.2 * 48000)
        assert np.all(np.isfinite(normal))

    def test_sweep_durations(self, template_path):
        scope = load_mix_module(template_path)
        sweep = scope["sweep"]

        test_durations = [-1.0, 0.0, 1e-5, None, "nan", float("nan")]
        for d in test_durations:
            res = sweep(200, 800, d)
            assert isinstance(res, np.ndarray)
            assert len(res) >= 1
            assert np.all(np.isfinite(res))

    def test_effects_negative_and_zero_durations(self, template_path):
        scope = load_mix_module(template_path)
        fx_dict = scope["FX"]

        parametric_fx = ["whoosh", "slide", "bubbles", "alarm", "sparkle", "sizzle", "inhale"]
        bad_durations = [-1.5, -0.001, 0.0, 0.0001, None, "invalid", float("nan")]

        for fx_name in parametric_fx:
            fn = fx_dict[fx_name]
            for d in bad_durations:
                res = fn(d=d)
                assert isinstance(res, np.ndarray), f"{fx_name} failed for dur={d}"
                assert len(res) > 0, f"{fx_name} returned empty array for dur={d}"
                assert np.all(np.isfinite(res)), f"{fx_name} produced non-finite values for dur={d}"

    def test_bubbles_short_duration_slice_safety(self, template_path):
        """Specifically tests that bubbles does not throw broadcast length mismatches on small d."""
        scope = load_mix_module(template_path)
        bubbles = scope["bubbles"]

        for d in [0.01, 0.05, 0.1, 0.15, 0.2]:
            res = bubbles(d=d)
            assert isinstance(res, np.ndarray)
            assert len(res) >= int(0.15 * 48000)
            assert np.all(np.isfinite(res))

    def test_all_fx_valid_outputs(self, template_path):
        """Verifies that all 16 sound effects run and produce valid non-empty audio."""
        scope = load_mix_module(template_path)
        fx_dict = scope["FX"]

        for name, fn in fx_dict.items():
            res = fn()
            assert isinstance(res, np.ndarray), f"Effect {name} returned non-array"
            assert len(res) > 0, f"Effect {name} returned empty array"
            assert np.all(np.isfinite(res)), f"Effect {name} contains NaN or Inf"
