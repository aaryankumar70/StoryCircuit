# CurioLoop generation engines

## Shared contracts and studio lanes

Both studios use `curiosity_engine.generation.engine_registry`. The dashboard bootstraps the concrete engines at startup without starting Ollama, downloading weights, changing publishing settings, or editing the database. Automatic Studio retains its topic selection, research, production queue, QC, and schedule flow. Creator Studio retains its approved episode workflow and independent queue. Rendering an episode does not enqueue, publish, or schedule it.

`OllamaScriptEngine` uses CurioLoop's existing `LocalModelAdapter`; `LOCAL_LLM_MODEL` selects the installed model. It reads supplied research dossiers, source ledgers, and discovery claims. Candidate strings without source references remain explicitly unverified; the engine does not upgrade them to verified evidence. Pydantic validates every model response, unknown source IDs fail closed, and malformed data receives at most three adapter attempts. Timing estimates use CurioLoop's calibrated spoken pace, sentence grouping, lead, outro, and pauses. Editorial scores are review heuristics, not predictions of views or virality.

`LOCAL_LLM_CONTEXT_SIZE` sets Ollama's `num_ctx` (default 8192; accepted range 4096-32768). The installed Qwen model supports 32K, but local Ollama was observed using 4096 and truncating structured scenes. The 8K default gives the prompt and response schema more room while keeping context use configurable for this 16 GB machine.

`LOCAL_LLM_MAX_OUTPUT_TOKENS` defaults to 1800 and accepts 1200-4096. Qwen returns the structured narrative and claims; CurioLoop normalizes narration-line strings or objects, then its offline Visual Director constructs and validates full scene directions from each line. This keeps CPU inference bounded without leaving scene fields blank. The engine rejects a result that does not retain any central topic or research-dossier term.

`Cartoon3DVisualEngine` implements the existing visual contract. The style selector currently returns only Cartoon 3D variations. The director groups narration-led shots, keeps approved scene instructions, and binds scene windows to Kokoro's final sentence timing. The composer draws original 2D cartoon characters in Three.js environments, with moving cameras, lighting, depth of field, story props, transitions, word captions, and narration-aware sound cues. Chromium captures frames and FFmpeg writes a 1080x1920, 30 FPS H.264/AAC MP4. This uses the existing Chromium/FFmpeg pipeline and vendored Three.js; it does not require Remotion, React, npm installs, or another renderer family.

Ollama, Kokoro, Whisper, Chromium/Three.js, and FFmpeg share the inter-process generation lock. The model adapter unloads Ollama after inference. Model weights stay in Ollama's external model store, and Kokoro/Whisper paths are under the configured models directory.

## Storage and resource limits

Set these environment variables before starting CurioLoop. Values are paths on the local machine:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CURIOLOOP_MODELS_DIR` | `D:\\yt\\models` | Local Kokoro and Whisper model files; Ollama weights remain in Ollama's store. |
| `CURIOLOOP_DATA_DIR` | `D:\\yt\\data` | SQLite, local state, and generation lock. |
| `CURIOLOOP_OUTPUT_DIR` | `D:\\yt\\output` | Projects, logs, and MP4 output. |
| `CURIOLOOP_RENDER_TMP_DIR` | OS temp `\\curioloop-render` | Isolated Chromium profiles and capture temp files. |
| `CURIOLOOP_RENDER_MAX_TMP_GB` | `8` | Active CurioLoop temp hard cap; maximum accepted value is 16 GiB. |
| `CURIOLOOP_RENDER_MIN_FREE_GB` | `5` | Free-space preflight at the temp location. |
| `CURIOLOOP_RENDER_MIN_OUTPUT_FREE_GB` | `2` | Free-space preflight at the output location. |
| `CURIOLOOP_RENDER_MAX_BUNDLE_MB` | `100` | Renderer bundle cap; maximum accepted value is 250 MiB. |
| `CURIOLOOP_RENDER_MAX_DURATION_SEC` | `60` | Render duration cap; CurioLoop's engine hard limit remains 60 seconds. |
| `CURIOLOOP_RENDER_TIMEOUT_SEC` | `3000` | Capture timeout, bounded to 30–7200 seconds. |
| `CURIOLOOP_FFPROBE` | `PATH` lookup | Optional explicit FFprobe executable when it is not beside/on the PATH with FFmpeg. |

Preflight estimates temp needs, checks both target volumes, and rejects cap violations before capture. During capture, CurioLoop monitors its owned temp directories, terminates the process tree if the cap is exceeded, and removes only its private, inactive temp/staging paths. A failed render leaves an existing MP4 intact. A stale render is reclaimed only after its owner processes are gone and it is at least 24 hours old. Renderer bundles over their configured cap are rejected.

## Qwen model and license gate

The default model is `qwen2.5:3b`, and the engine never downloads or replaces it. Qwen's [published Qwen2.5-3B license](https://huggingface.co/Qwen/Qwen2.5-3B/blob/main/LICENSE) is a research license; it defines non-commercial use as research or evaluation purposes and requires a separate license for commercial use. Qwen's [Qwen2.5 release notes](https://qwenlm.github.io/blog/qwen2.5-llm/) describe the 3B model and 32K context. The model can remain installed, but this configuration does not clear it for monetized or other commercial production. The engine therefore stays in safe standby unless the process environment explicitly opts into personal, non-commercial experimentation. That opt-in records an operator choice; it does not decide whether a particular use is legally permitted.

Other models also remain in standby until the operator supplies the model's assessed license and acknowledges that assessment. The code does not download a substitute or claim to verify a license automatically. Review the exact license for any replacement before selecting it.

## Manual personal-experiment activation

The default activation is blank. For personal, non-commercial experimentation only, open PowerShell and set the flags in the same process that launches CurioLoop:

```powershell
$env:LOCAL_LLM_MODEL = 'qwen2.5:3b'
$env:LOCAL_LLM_CONTEXT_SIZE = '8192'
$env:OLLAMA_AUTOSTART = '0'
$env:CURIOLOOP_ENGINE_ACTIVATION = 'personal_non_commercial_experimentation'
$env:CURIOLOOP_ACK_QWEN_RESEARCH_LICENSE = 'YES'
Set-Location D:\yt
python scripts\run_dashboard.py
```

Confirm Ollama is already running and `qwen2.5:3b` is already installed before triggering a local generation. No weights are fetched by CurioLoop. Do not use these Qwen flags for monetized or other commercial output. For production, leave Qwen gated and first select a model whose specific license clearly permits the intended use. Do not start the scheduler daemon for a render-only check; the dashboard and direct render workflows do not need a new scheduler process.

## Reference and third-party notices

The renderer's story-driven cartoon direction was informed by `claude-animated-shorts-main` (MIT, Mr omi, 2026). Its Remotion code, sample short, reference frames, contact sheets, and fonts are not bundled here. Its included private-study reference images are not used. The current integration reuses CurioLoop's Chromium/FFmpeg capture contract and does not depend on Remotion's runtime.

The hook, title, retention, outlier, planning, and audit utilities are small local adaptations informed by `youtube-agent-skill-main` (MIT, Jake Schincariol, 2026). Adaptations distinguish editorial heuristics from analytics; they do not fabricate performance data. The required MIT notice is in `docs/third_party/YOUTUBE_AGENT_LICENSE.txt`.

Three.js and its postprocessing modules are vendored under `templates/cartoon-3d/vendor`; their MIT notice is `templates/cartoon-3d/vendor/LICENSE-three.txt`. No unlicensed/sample visual assets are included.
