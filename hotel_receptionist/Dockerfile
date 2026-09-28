# syntax=docker/dockerfile:1
# LiveKit Cloud agent image for the cloud demo (issue #16). Based on `lk agent dockerfile`.
# Cloud backends only: base requirements.txt, no MLX. Configuration comes from agent secrets
# (AGENT_NAME, AGENT_LANGUAGE); LiveKit Cloud injects its own credentials.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim AS base
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

FROM base AS build
RUN apt-get update && apt-get install -y gcc g++ python3-dev \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt constraints-cloud.txt ./
RUN python -m venv .venv
ENV PATH="/app/.venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt -c constraints-cloud.txt
# Pre-download turn-detector / VAD model files (cached across code-only changes).
RUN python -m livekit.agents download-files
COPY . .

FROM base
ARG UID=10001
RUN adduser --disabled-password --gecos "" --home "/app" --shell "/sbin/nologin" --uid "${UID}" appuser
WORKDIR /app
COPY --from=build --chown=appuser:appuser /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER appuser
CMD ["python", "agent.py", "start"]
