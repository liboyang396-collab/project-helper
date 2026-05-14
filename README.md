# Project Helper 项目学习助手

Project Helper 是一个基于 **FastAPI + Vue** 的开源项目学习助手，用来帮助用户快速读懂陌生 GitHub 仓库的源码。

用户只需要输入一个 GitHub 仓库地址，系统就会自动克隆项目、扫描源码、生成通俗易懂的分析报告，并支持围绕源码进行交互式问答。后端会把分析结果缓存到 SQLite，已经分析过的项目无需重复分析。

## 核心功能

- 输入 GitHub 仓库地址后自动克隆并分析源码。
- 生成完整项目分析报告，覆盖项目概述、技术栈、目录结构、核心模块、数据流、设计模式和阅读建议。
- 分析过程通过 SSE 实时推送进度。
- 使用 SQLite 缓存历史分析结果。
- 源码问答 Agent 支持读取文件、搜索代码，并基于真实源码回答问题。
- 前端支持 Markdown 渲染和代码高亮，适合阅读长篇分析报告。
- 支持 DeepSeek、Xiaomi MiMo、火山方舟 Ark 等模型提供方。

## 技术栈

后端：

- Python
- FastAPI
- LangChain
- SQLite / SQLAlchemy
- DeepSeek / MiMo / Volcengine Ark

前端：

- Vue 3
- Vite
- TypeScript
- markdown-it
- highlight.js
- lucide-vue-next

## 快速启动

先复制环境变量文件：

```bash
cp backend/.env.example backend/.env
```

启动后端：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

另开一个终端启动前端：

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器打开：

```text
http://127.0.0.1:5173
```

## 模型配置

复制 `backend/.env.example` 为 `backend/.env` 后，选择一个模型提供方。

### DeepSeek

```bash
MODEL_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

### Xiaomi MiMo

MiMo 使用 OpenAI 兼容接口：

```bash
MODEL_PROVIDER=mimo
MIMO_API_KEY=your_mimo_api_key
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2.5
MIMO_DISABLE_THINKING=true
```

### 火山方舟 Ark Responses API

```bash
MODEL_PROVIDER=ark
ARK_API_KEY=your_ark_api_key
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3/responses
ARK_MODEL=doubao-seed-2-0-mini-260215
ARK_ENABLE_WEB_SEARCH=false
```

如果没有配置可用 API Key，项目仍然可以启动，并会基于本地源码扫描生成确定性的基础分析结果。

## 使用方式

1. 打开前端页面。
2. 输入一个 GitHub 仓库地址，例如：

```text
https://github.com/liyupi/ai-guide
```

3. 点击开始分析。
4. 等待进度完成后查看项目学习报告。
5. 在源码问答区域提问，例如：

```text
这个项目的入口文件在哪里？
我应该先读哪些文件？
这个项目怎么运行？
核心模块之间是怎么协作的？
```

## 部署说明

GitHub Pages 只能部署静态前端，不能运行 FastAPI 后端。

如果要完整上线，推荐：

- 前端部署到 GitHub Pages、Vercel 或 Netlify。
- 后端部署到 Render、Railway、Fly.io、云服务器或其他 Python 服务平台。
- 前端通过 API 地址访问后端服务。

## 安全说明

- `backend/.env` 用于保存真实 API Key，已经被 `.gitignore` 忽略，不应提交到 GitHub。
- `backend/.env.example` 只保留示例配置，不包含真实密钥。
- 公开仓库前请确认没有提交数据库、缓存目录、仓库克隆目录或真实密钥。

## 项目结构

```text
project-helper/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── config.py            # 配置读取
│   │   ├── database.py          # 数据库连接
│   │   ├── models.py            # SQLAlchemy 模型
│   │   ├── schemas.py           # API 数据结构
│   │   └── services/
│   │       ├── analyzer.py      # 项目分析逻辑
│   │       ├── llm.py           # 模型提供方封装
│   │       ├── qa_agent.py      # 源码问答 Agent
│   │       ├── repository.py    # Git 仓库克隆与刷新
│   │       └── source_scan.py   # 源码扫描
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.vue
│   │   ├── components/
│   │   ├── services/
│   │   └── styles/
│   ├── package.json
│   └── vite.config.ts
└── README.md
```
