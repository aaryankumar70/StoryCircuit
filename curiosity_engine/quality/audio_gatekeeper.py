"""CurioLoop 2.0 Audio Gatekeeper.
Strictly protects video production assembly from test audio, dead air, silent stems, or clipping.
Adapted from toolkit production gatekeeper for zero-cost local Kokoro ONNX audio pipelines.
"""
from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union
import numpy as np

logger = logging.getLogger(__name__)


class AudioGatekeeperError(RuntimeError):
    """Raised when audio fails strict quality or integrity thresholds."""
    pass


class AudioGatekeeper:
    """Production audio gatekeeper enforcing real narration standards."""

    @staticmethod
    def verify_audio_file(
        wav_path: Union[str, Path],
        min_duration_sec: float = 1.0,
        max_duration_sec: float = 120.0,
        allow_synthetic_test: bool = False,
    ) -> Dict[str, Any]:
        """Validates a WAV stem on disk for amplitude, energy, duration, and clipping.
        
        Args:
            wav_path: Path to .wav file.
            min_duration_sec: Minimum acceptable duration in seconds.
            max_duration_sec: Maximum acceptable duration in seconds.
            allow_synthetic_test: If False, blocks test tones or mock stems.
            
        Returns:
            Dict containing audio metrics (duration_sec, peak_amplitude, rms, sample_rate, channels).
        """
        path = Path(wav_path)
        if not path.exists():
            raise AudioGatekeeperError(f"Audio file not found: {path}")

        try:
            with wave.open(str(path), "rb") as wf:
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                sample_rate = wf.getframerate()
                n_frames = wf.getnframes()
                raw_bytes = wf.readframes(n_frames)
        except Exception as e:
            raise AudioGatekeeperError(f"Failed to read WAV header for {path}: {e}") from e

        if n_frames == 0 or sample_rate == 0:
            raise AudioGatekeeperError(f"Corrupt or empty WAV file: {path}")

        duration_sec = n_frames / float(sample_rate)
        if duration_sec < min_duration_sec:
            raise AudioGatekeeperError(
                f"Audio duration {duration_sec:.2f}s is below minimum threshold {min_duration_sec:.2f}s."
            )
        if duration_sec > max_duration_sec:
            raise AudioGatekeeperError(
                f"Audio duration {duration_sec:.2f}s exceeds maximum threshold {max_duration_sec:.2f}s."
            )

        # Parse samples into numpy array based on sample width
        if sample_width == 2:  # 16-bit PCM
            samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        elif sample_width == 4:  # 32-bit PCM
            samples = np.frombuffer(raw_bytes, dtype=np.int32).astype(np.float32) / 2147483648.0
        elif sample_width == 1:  # 8-bit unsigned
            samples = (np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        else:
            raise AudioGatekeeperError(f"Unsupported sample bit-depth: {sample_width * 8}-bit")

        if len(samples) == 0:
            raise AudioGatekeeperError("Audio stream contains zero samples.")

        peak_amplitude = float(np.max(np.abs(samples)))
        rms = float(np.sqrt(np.mean(samples**2)))

        # Digital silence check (dead air)
        if peak_amplitude < 0.005:
            raise AudioGatekeeperError(
                f"PRODUCTION REJECTION: Audio contains zero signal energy (silent stem: peak={peak_amplitude:.5f})."
            )

        # Digital clipping check
        if peak_amplitude > 0.999:
            raise AudioGatekeeperError(
                f"PRODUCTION REJECTION: Audio contains severe digital clipping (peak={peak_amplitude:.4f} > 0.999)."
            )

        # Basic synthetic pure-tone detection (detecting mock sine waves)
        if not allow_synthetic_test and len(samples) > sample_rate:
            # Check zero-crossing periodicity of pure tones
            zero_crossings = np.nonzero(np.diff(samples > 0))[0]
            if len(zero_crossings) > 100:
                diffs = np.diff(zero_crossings)
                if np.std(diffs) < 0.1:  # Machine-regular periodicity indicates synthetic test tone
                    raise AudioGatekeeperError(
                        "PRODUCTION REJECTION: Audio pattern matches synthetic calibration tone."
                    )

        return {
            "path": str(path),
            "duration_sec": round(duration_sec, 3),
            "peak_amplitude": round(peak_amplitude, 4),
            "rms": round(rms, 4),
            "sample_rate": sample_rate,
            "channels": channels,
            "passed": True,
        }


# Global instance
audio_gatekeeper = AudioGatekeeper()
