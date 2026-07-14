"""Higgs Audio v3 TTS-4B RunEngine (engine mode).

Wraps FlashRT's HiggsAudioV3TorchFrontendRtx standalone frontend.
flashcli parses ``run_options`` and passes ``phase=load`` options to ``load()``
and ``phase=predict`` options to ``predict()``; defaults come from the manifest.
"""

from __future__ import annotations

import time
import wave
from pathlib import Path
from typing import Any

from flashcli_bundle.context import active_bundle
from flashcli_bundle.options import option_value, run_option_defaults


def _save_wav(path: str, wav, sample_rate: int = 24_000) -> None:
    import numpy as np

    x = (np.clip(wav.numpy() if hasattr(wav, "numpy") else wav, -1.0, 1.0)
         * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(x.tobytes())


class RunEngine:
    """Higgs Audio v3 TTS-4B text-to-speech engine."""

    def __init__(self) -> None:
        self._fe: Any = None
        self._defaults: dict[str, Any] = {}

    def load(self, checkpoint: Path, preset: Any, **options: Any) -> None:
        from flash_rt.frontends.torch.higgs_audio_v3_rtx import (
            HiggsAudioV3TorchFrontendRtx,
        )

        bundle = active_bundle()
        if bundle is not None:
            self._defaults = run_option_defaults(bundle)

        fp8_raw = str(option_value("fp8", options, self._defaults) or "auto")
        if fp8_raw.lower() in ("false", "0", "bf16", "no"):
            fp8 = False
        elif fp8_raw.lower() in ("true", "1", "fp8", "yes"):
            fp8 = True
        else:
            fp8 = None

        device = str(option_value("device", options, self._defaults) or "cuda:0")
        max_seq = int(option_value("max_seq", options, self._defaults) or 2048)

        t0 = time.perf_counter()
        self._fe = HiggsAudioV3TorchFrontendRtx(
            str(Path(checkpoint).expanduser().resolve()),
            device=device,
            max_seq=max_seq,
            fp8=fp8,
        )
        backbone = "BF16" if not self._fe.fp8 else "FP8 W8A8"
        print(f"[higgs_audio] load {backbone} {time.perf_counter() - t0:.1f}s")

    def predict(self, **kwargs: Any) -> dict[str, Any]:
        if self._fe is None:
            raise RuntimeError("RunEngine.load() not called before predict()")

        d = self._defaults
        text = str(option_value("text", kwargs, d))
        out = str(option_value("out", kwargs, d) or "output.wav")

        t0 = time.perf_counter()
        wav = self._fe.generate(text)
        dt = time.perf_counter() - t0
        _save_wav(out, wav)

        dur = len(wav) / 24_000
        frames_info = ""
        if self._fe.latency_records:
            ms = self._fe.latency_records[-1]
            n = max(1, int(round(dur * 25)))
            frames_info = f"  decode {ms:.0f}ms ({ms / n:.2f}ms/frame)"
        backbone = "BF16" if not self._fe.fp8 else "FP8 W8A8"
        print(f"[higgs_audio] [{backbone}] '{text[:60]}'")
        print(f"  -> {out}  ({dur:.1f}s audio, {dt:.1f}s wall){frames_info}")

        return {
            "out": str(Path(out).resolve()),
            "duration": dur,
            "wall_seconds": dt,
            "fp8": self._fe.fp8,
        }
