"""Code shared by the voice-agent apps in this repo (hotel_receptionist, bendon_ordering).

- ``profiles``   per-language speech/model defaults (``AGENT_LANGUAGE`` = en | zh | zh-tw)
- ``backends``   cloud (LiveKit Inference) / local (MLX) STT, LLM and TTS builders, session
                 connect options and worker options (``*_BACKEND`` / ``AGENT_*`` env vars)
- ``local_stt``  in-process MLX STT plugins (Qwen3-ASR batch, Nemotron streaming)

Apps import it via the repo root on ``sys.path`` (see ``ensure_importable`` in each app's
agent.py). LiveKit Cloud builds only see the app folder, so ``deploy/agent_deploy.sh`` copies
this package into the app just for the build.
"""
