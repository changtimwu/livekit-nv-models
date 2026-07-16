# Copilot Chat Conversation Export: Hosting hotel receptionist example locally

**User:** @timwu-ipevo
**Thread URL:** https://github.com/copilot/c/506284c2-d26f-4a7a-91b3-e81c8f44a0e8

## @timwu-ipevo

these examples are so amazing.  any possible I host one with my own GPU?  I'd like to run my live audio app with a local hosted Nemotron 3 ASR model

## Copilot

Yes! You can absolutely host the hotel_receptionist example on your own GPU with a local Nemotron 3 ASR model. Here's how to approach it:

## Key Architecture Points

Looking at the `agent.py`, the example currently uses:
- **STT**: `deepgram/nova-3` (speech-to-text)
- **LLM**: `google/gemma-4-31b-it` (language model)
- **TTS**: `inworld/inworld-tts-2` (text-to-speech)
- **VAD**: `silero` (voice activity detection)

## To Use Local Nemotron 3 ASR

You'll need to swap out the STT component. Here's the relevant section from `agent.py` (lines 220-225):

```python
session = AgentSession[Userdata](
    userdata=userdata,
    vad=inference.VAD(model="silero"),
    stt=inference.STT("deepgram/nova-3"),  # ← Replace this
    llm=inference.LLM("google/gemma-4-31b-it"),
    tts=inference.TTS("inworld/inworld-tts-2"),
    max_tool_steps=5,
)
```

## Steps to Get It Running Locally

1. **Check LiveKit Agents documentation** for local model support. The framework likely has plugins for local inference servers (Ollama, vLLM, etc.). You may need to:
   - Use a local inference server for Nemotron 3 (via Ollama, vLLM, or similar)
   - Replace `inference.STT("deepgram/nova-3")` with a custom STT plugin pointing to your local Nemotron endpoint

2. **Install LiveKit Agents with local GPU support**:
   ```bash
   uv sync --all-extras --dev
   ```

3. **Modify the agent.py** to use your local models instead of cloud providers

4. **Set up environment variables** for your local server endpoints instead of cloud API keys

5. **Run it**:
   ```bash
   python examples/hotel_receptionist/agent.py console
   ```

## Recommendation

I'd suggest checking the **[LiveKit Agents documentation](https://docs.livekit.io/agents/)** for:
- Custom STT integration patterns
- Local inference server setup guides  
- Which model providers have local/self-hosted variants

The framework is designed to be pluggable, so swapping Deepgram for Nemotron should be straightforward once you know the exact plugin/API pattern used. Would you like me to search for any specific local inference integration examples in the repo?

## @timwu-ipevo

can I also change the TTS model to a local hosted one?  does it support this nvidia model?  https://huggingface.co/nvidia/magpie_tts_multilingual_357m 

## Copilot

Yes, you can use a local TTS model! LiveKit Agents has a **plugin-based architecture** that supports many TTS providers, including local inference options. Let me show you what's available and how to use Nvidia's Magpie TTS.

## Available Local/Self-Hosted TTS Options

LiveKit Agents supports several models that can run locally or on your own infrastructure:

1. **Custom HTTP endpoints** — You can wrap any local model (including Magpie TTS) with a simple HTTP server and point the plugin to it
2. **SimpliSmart plugin** — Supports local Orpheus models and Qwen 3 TTS with custom `base_url` parameter
3. **Baseten plugin** — Can host models on your own infrastructure with a custom endpoint

## Using Nvidia Magpie TTS with a Local Endpoint

Here's how to adapt the hotel receptionist agent for local Magpie TTS:

```python
# Instead of:
tts=inference.TTS("inworld/inworld-tts-2")

# Use SimpliSmart with your local Magpie server:
from livekit.plugins import simplismart

tts=simplismart.TTS(
    base_url="http://localhost:8000",  # Your local Magpie TTS server
    model="magpie_tts_multilingual_357m",
    voice="default",  # or your preferred voice
    sample_rate=24000,
)
```

## Setting Up a Local Magpie TTS Server

You'll need to create a simple inference server wrapper around the Magpie model. Here's a basic example using FastAPI:

```python
# tts_server.py
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import torch
from transformers import AutoModel, AutoTokenizer
import io

app = FastAPI()

# Load Magpie model
model = AutoModel.from_pretrained(
    "nvidia/magpie_tts_multilingual_357m",
    trust_remote_code=True
).to("cuda")

@app.post("/v1/tts")
async def synthesize(text: str, voice: str = "default"):
    # Your Magpie synthesis logic here
    audio_output = model.synthesize(text)
    
    # Return as audio stream
    buffer = io.BytesIO()
    # Save audio to buffer (WAV, MP3, etc.)
    return StreamingResponse(buffer, media_type="audio/wav")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8000)
```

## Alternative: Custom TTS Plugin

If you want more control, you can create a custom TTS plugin by extending `livekit.agents.tts.TTS`:

```python
from livekit.agents import tts
import aiohttp

class MagpieTTS(tts.TTS):
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self._session = None
    
    @property
    def sample_rate(self) -> int:
        return 24000
    
    @property
    def model(self) -> str:
        return "magpie_tts_multilingual_357m"
    
    async def synthesize(self, text: str) -> tts.ChunkedStream:
        # Implement synthesis logic
        pass
```

## Modified Agent Configuration

Update your `agent.py`:

```python
from livekit.plugins import simplismart
from livekit.agents import inference

# In the hotel_receptionist_agent function:
session = AgentSession[Userdata](
    userdata=userdata,
    vad=inference.VAD(model="silero"),
    stt=inference.STT("deepgram/nova-3"),  # Keep cloud STT or use local Nemotron
    llm=inference.LLM("google/gemma-4-31b-it"),
    tts=simplismart.TTS(
        base_url="http://localhost:8000",  # Your local Magpie server
        model="magpie_tts_multilingual_357m",
        voice="female",  # Adjust voice ID
        sample_rate=24000,
    ),
    max_tool_steps=5,
)
```

The key advantage of this approach is that **all audio processing happens locally on your GPU**, with no dependency on external cloud TTS services.

## @timwu-ipevo

and my LLM gemma-4-31b-it  is also local hosted.  it's nvidia's port https://huggingface.co/nvidia/Gemma-4-31B-IT-NVFP4 

## Copilot

Perfect! LiveKit has excellent support for OpenAI-compatible endpoints, which is exactly what you need for your local Gemma-4 31B. Here's how to set it up:

## Using Local Nvidia Gemma-4 31B

The OpenAI plugin in LiveKit supports `base_url` parameter for custom endpoints. You can point it to any OpenAI-compatible server hosting your local model.

### Modified Agent Configuration

```python
from livekit.plugins import openai
from livekit.agents import inference

# In your hotel_receptionist_agent function:
session = AgentSession[Userdata](
    userdata=userdata,
    vad=inference.VAD(model="silero"),
    stt=inference.STT("deepgram/nova-3"),  # or local Nemotron
    llm=openai.LLM(
        model="nvidia/gemma-4-31b-it",  # Model identifier (can be any string)
        base_url="http://localhost:8000/v1",  # Your local server endpoint
        api_key="not-needed",  # Some servers don't require this; adjust as needed
    ),
    tts=simplismart.TTS(
        base_url="http://localhost:9000",  # Your local Magpie server
        model="magpie_tts_multilingual_357m",
        voice="default",
        sample_rate=24000,
    ),
    max_tool_steps=5,
)
```

## Setting Up Your Local LLM Server

You'll need to run your Nvidia Gemma-4 model through an OpenAI-compatible inference server. Here are the most common options:

### Option 1: vLLM (Recommended)

```bash
pip install vllm
python -m vllm.entrypoints.openai.api_server \
    --model nvidia/Gemma-4-31B-IT-NVFP4 \
    --dtype bfloat16 \
    --port 8000 \
    --gpu-memory-utilization 0.9
```

Then use:
```python
llm=openai.LLM(
    model="nvidia/Gemma-4-31B-IT-NVFP4",
    base_url="http://localhost:8000/v1",
    api_key="not-needed",
)
```

### Option 2: Ollama

```bash
ollama pull nvidia/gemma-4-31b-it
ollama serve  # Runs on http://localhost:11434
```

Then use the built-in Ollama helper:
```python
llm=openai.LLM.with_ollama(
    model="nvidia/gemma-4-31b-it",
    base_url="http://localhost:11434/v1",
)
```

### Option 3: LM Studio or Text Generation WebUI

Both support OpenAI-compatible APIs. Just point to their local endpoint (typically `http://localhost:8000/v1` or `http://localhost:5000/v1`).

## Complete Local Setup

Here's the full modified `agent.py` for your fully local setup:

```python
from livekit.plugins import openai, simplismart
from livekit.agents import inference

# ... existing imports ...

@server.rtc_session(on_session_end=on_session_end, on_simulation_end=on_simulation_end)
async def hotel_receptionist_agent(ctx: JobContext) -> None:
    await ctx.connect()

    db = HotelDB.from_bytes(_SEED_DB_BYTES)
    ui = UiView(ctx.room, db.connection)
    db.on_change = ui.on_change
    await ui.start()

    userdata = Userdata(db=db)
    session = AgentSession[Userdata](
        userdata=userdata,
        vad=inference.VAD(model="silero"),
        
        # Local STT (Nemotron 3)
        stt=openai.STT(
            model="nemotron-3-asr",
            base_url="http://localhost:9001/v1",  # Your Nemotron server
            api_key="not-needed",
        ),
        
        # Local LLM (Nvidia Gemma-4)
        llm=openai.LLM(
            model="nvidia/Gemma-4-31B-IT-NVFP4",
            base_url="http://localhost:8000/v1",  # Your vLLM server
            api_key="not-needed",
        ),
        
        # Local TTS (Nvidia Magpie)
        tts=simplismart.TTS(
            base_url="http://localhost:9000",
            model="magpie_tts_multilingual_357m",
            voice="default",
            sample_rate=24000,
        ),
        
        max_tool_steps=5,
    )

    await session.start(agent=HotelReceptionistAgent(), room=ctx.room)
```

## Running Everything Locally

Start your services in separate terminals:

```bash
# Terminal 1: vLLM with Gemma-4
python -m vllm.entrypoints.openai.api_server \
    --model nvidia/Gemma-4-31B-IT-NVFP4 \
    --dtype bfloat16 \
    --port 8000

# Terminal 2: Your Magpie TTS server (from earlier)
python tts_server.py

# Terminal 3: Your agent
python examples/hotel_receptionist/agent.py console
```

This gives you complete local control over the AI pipeline with **zero cloud dependencies**!
