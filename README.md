# Project Helper

Project Helper is a FastAPI + Vue web app for learning unfamiliar open-source projects quickly.

Users paste a GitHub repository URL, the backend clones and analyzes the codebase, caches the report in SQLite, streams progress to the browser, and exposes a source-aware Q&A agent with file reading and code search tools.

## Quick Start

```bash
cp backend/.env.example backend/.env

cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`.

## Model Providers

Copy `backend/.env.example` to `backend/.env`, then choose one provider.

DeepSeek:

```bash
MODEL_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

Xiaomi MiMo OpenAI-compatible API:

```bash
MODEL_PROVIDER=mimo
MIMO_API_KEY=your_mimo_api_key
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2.5
MIMO_DISABLE_THINKING=true
```

Volcengine Ark Responses API:

```bash
MODEL_PROVIDER=ark
ARK_API_KEY=your_ark_api_key
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/responses
ARK_MODEL=deepseek-v3-2-251201
ARK_ENABLE_WEB_SEARCH=false
```

Without a key, the app still runs and produces deterministic local analysis from the repository contents.
