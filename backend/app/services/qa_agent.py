from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import AsyncIterator

from langchain.agents import AgentType, initialize_agent
from langchain.tools import Tool

from app.models import Project
from app.services.llm import get_openai_compatible_chat, is_ark_enabled, selected_provider, stream_text
from app.services.source_scan import IGNORE_DIRS, iter_source_files, safe_read


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _safe_path(root: Path, relative_path: str) -> Path:
    target = (root / relative_path).resolve()
    root_resolved = root.resolve()
    if target != root_resolved and root_resolved not in target.parents:
        raise ValueError("Path is outside repository.")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(relative_path)
    return target


def _clean_tool_input(value: str) -> str:
    cleaned = value.strip().strip("`").strip()
    quote_pairs = (("'", "'"), ('"', '"'), ("“", "”"), ("‘", "’"))
    changed = True
    while changed and len(cleaned) >= 2:
        changed = False
        for left, right in quote_pairs:
            if cleaned.startswith(left) and cleaned.endswith(right):
                cleaned = cleaned[1:-1].strip()
                changed = True
                break
    return cleaned


def _rg_ignore_args() -> list[str]:
    glob_args = []
    for directory in IGNORE_DIRS:
        glob_args.extend(["--glob", f"!{directory}", "--glob", f"!**/{directory}/**"])
    return glob_args


def _local_answer(project: Project, question: str, reason: str = "missing_key") -> str:
    root = Path(project.local_path)
    query = question.strip()
    files = list(iter_source_files(root))[:300]
    matches: list[str] = []

    for token in [part for part in query.replace("？", " ").replace("?", " ").split() if len(part) >= 3][:6]:
        try:
            result = subprocess.run(
                ["rg", "--line-number", "--no-heading", *_rg_ignore_args(), token, str(root)],
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            matches.extend(result.stdout.replace(str(root) + "/", "").splitlines()[:8])
        except Exception:
            continue

    file_list = "\n".join(f"- `{path.relative_to(root).as_posix()}`" for path in files[:40])
    match_text = "\n".join(f"- `{line}`" for line in matches[:30]) or "- 暂未匹配到明显代码行"
    provider = selected_provider()
    key_hints = {
        "deepseek": "`DEEPSEEK_API_KEY`",
        "ark": "`ARK_API_KEY`",
        "mimo": "`MIMO_API_KEY`",
    }
    key_hint = key_hints.get(provider, "`DEEPSEEK_API_KEY` / `ARK_API_KEY` / `MIMO_API_KEY`")
    if reason == "missing_key":
        intro = f"当前没有配置可用的 {provider} API Key，所以我先用本地搜索给你一个可验证的回答。"
        outro = f"配置 {key_hint} 后，我可以调用模型结合源码上下文给出更像导师一样的解释。"
    else:
        intro = "AI Agent 暂时调用失败，所以我先用本地搜索给你一个可验证的回答。"
        outro = "你可以稍后重试，或者换一个更具体的问题让我继续查源码。"

    return f"""{intro}

你的问题：{question}

建议先检查这些文件：

{file_list}

相关搜索命中：

{match_text}

{outro}"""


def _is_usage_question(question: str) -> bool:
    normalized = question.lower()
    return any(word in normalized for word in ("怎么使用", "如何使用", "怎么运行", "如何运行", "quickstart", "usage", "run"))


def _looks_like_internal_answer(answer: str) -> bool:
    if not answer.strip():
        return True
    markers = (
        "调用web_search",
        "用户的问题",
        "用户现在",
        "应该先调用",
        "需要确认一下",
        "不要编造",
        "不过现在",
        "有没有需要调用工具",
        "最终的回答应该是",
        "现在整理成中文",
        "哦，对了",
        "哦对了",
        "用户给",
        "源码列表",
        "搜索命中",
        "应该优先",
        "不过还要注意",
        "有没有其他文件",
        "也就是FastAPI的使用方法",
    )
    return any(marker in answer for marker in markers)


def _usage_answer(project: Project) -> str:
    root = Path(project.local_path)
    important = [
        "README.md",
        "README.zh-CN.md",
        "README_zh.md",
        "docs/index.md",
        "docs/en/docs/index.md",
        "pyproject.toml",
        "requirements.txt",
        "package.json",
        "Dockerfile",
        "docker-compose.yml",
        "compose.yml",
    ]
    existing = [path for path in important if (root / path).exists()]
    test_examples = sorted(path.relative_to(root).as_posix() for path in root.glob("tests/test*.py"))[:4]

    readme = next((path for path in existing if path.lower().startswith("readme")), None)
    package_json = root / "package.json"
    scripts = ""
    if package_json.exists():
        try:
            package = json.loads(safe_read(package_json, 30000))
            script_items = (package.get("scripts") or {}).items()
            scripts = "、".join(f"`npm run {name}`" for name, _ in list(script_items)[:5])
        except json.JSONDecodeError:
            scripts = ""

    steps = []
    if readme:
        steps.append(f"1. **先看入口文档**：打开`{readme}`，这里通常是项目的快速开始、安装方式和核心概念入口。")
    elif existing:
        steps.append(f"1. **先看关键文件**：从`{existing[0]}`开始，它最可能说明项目的安装和启动方式。")
    else:
        steps.append("1. **先看根目录文件**：优先找`README`、`docs/`、依赖配置文件和入口文件。")

    install_hints = []
    if (root / "pyproject.toml").exists():
        install_hints.append("Python项目通常可以先执行`pip install -e .`安装本地源码包")
    if (root / "requirements.txt").exists():
        install_hints.append("如果有`requirements.txt`，执行`pip install -r requirements.txt`安装依赖")
    if package_json.exists():
        install_hints.append("如果需要前端或Node脚本，先执行`npm install`")
    if (root / "docker-compose.yml").exists() or (root / "compose.yml").exists():
        install_hints.append("如果项目提供Compose配置，可以用`docker compose up`启动依赖服务")
    if install_hints:
        steps.append("2. **安装依赖**：" + "；".join(install_hints) + "。")

    if scripts:
        steps.append(f"3. **运行脚本**：`package.json`里能看到这些常用脚本：{scripts}。")
    else:
        steps.append("3. **找启动入口**：查看`pyproject.toml`、`package.json`、`main.py`、`app.py`或`docs/`里的启动说明。")

    if test_examples:
        examples = "、".join(f"`{path}`" for path in test_examples)
        steps.append(f"4. **看示例和验证行为**：`tests/`目录里的测试就是最可靠的使用样例，可以先读{examples}。")

    files = "、".join(f"`{path}`" for path in existing[:8])
    if files:
        steps.append(f"5. **建议阅读顺序**：{files}。")

    return "\n".join(steps)


def _question_context(project: Project, question: str) -> str:
    root = Path(project.local_path)
    files = list(iter_source_files(root))[:160]
    matches: list[str] = []
    for token in [part for part in question.replace("？", " ").replace("?", " ").split() if len(part) >= 3][:8]:
        try:
            result = subprocess.run(
                ["rg", "--line-number", "--no-heading", *_rg_ignore_args(), token, str(root)],
                text=True,
                capture_output=True,
                timeout=6,
                check=False,
            )
            matches.extend(result.stdout.replace(str(root) + "/", "").splitlines()[:12])
        except Exception:
            continue

    file_list = "\n".join(path.relative_to(root).as_posix() for path in files[:90])
    match_text = "\n".join(matches[:80]) or "未搜索到直接命中的代码行。"
    return f"""仓库：{project.repo_url}
本地路径：{root}

源码文件列表节选：
```text
{file_list}
```

问题相关搜索命中：
```text
{match_text}
```
"""


def _clean_answer(text: str, question: str = "") -> str:
    original = text.strip()
    cleaned = original
    for marker in (
        "现在整理一下：",
        "现在整理一下:",
        "整理一下：",
        "整理一下:",
        "回答：",
        "回答:",
        "正确的回答应该是：",
        "正确的回答应该是:",
        "最终的回答应该是：",
        "最终的回答应该是:",
        "总结一句话的话，应该是：",
        "总结一句话的话，应该是:",
        "现在整理成中文，通俗的解释：",
        "现在整理成中文，通俗的解释:",
        "整理成中文，通俗的解释，符合要求：",
        "整理成中文，通俗的解释，符合要求:",
    ):
        if marker in cleaned:
            cleaned = cleaned.rsplit(marker, 1)[-1]
    cleaned = _truncate_meta_tail(cleaned)
    cleaned = re.sub(r"^(用户现在需要|用户现在问的是|我需要|我们需要).*?[。！？]", "", cleaned)
    cleaned = re.sub(r"^(所以)?总结一句话的话[，,：:]?", "", cleaned)
    cleaned = re.sub(r"^比如[，,：:]?", "", cleaned)
    cleaned = re.sub(r"^(首先，|首先,|不过首先，|不过首先,)", "", cleaned)
    cleaned = re.sub(r"(对，?应该这样|对，?这样|整理成通顺的一句话|那现在.*?回答|正确的一句话回答应该是).*?[。！？]", "", cleaned)
    cleaned = re.sub(r"(不对，?|等等，?|等一下，?|不过等一下，?|那现在按照要求).*?[。！？]", "", cleaned)
    cleaned = _trim_repeated_answer_block(cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    cleaned = cleaned.lstrip("，,。；;：: ")
    sentences = [part for part in re.split(r"(?<=[。！？])", cleaned) if part.strip()]
    draft_prefixes = (
        "用户现在需要",
        "首先",
        "先来",
        "我需要",
        "我们需要",
        "正确的回答",
        "应该这样",
        "或者更",
        "要不要",
        "不过等一下",
        "确认一下",
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        stripped_sentence = sentence.strip()
        if any(stripped_sentence.startswith(prefix) for prefix in draft_prefixes):
            continue
        normalized = re.sub(r"\s+", "", sentence)
        if normalized not in seen:
            seen.add(normalized)
            deduped.append(sentence)
    if deduped:
        cleaned = "".join(deduped).strip()
    cleaned = _truncate_meta_tail(cleaned)
    cleaned = _trim_repeated_answer_block(cleaned)
    if any(word in question for word in ("一句话", "简短", "简要")):
        short_sentences = [part for part in re.split(r"(?<=[。！？])", cleaned) if part.strip()]
        if short_sentences:
            cleaned = short_sentences[0].strip()
    return cleaned or original


def _truncate_meta_tail(text: str) -> str:
    markers = (
        "\n\n不过现在，按照系统提示",
        "\n\n另外，有没有需要调用工具",
        "\n\n不过有没有需要调用工具",
        "\n\n有没有需要调用工具",
        "\n\n这样就可以了",
        "\n\n不过等一下",
        "\n\n那现在按照要求",
        "\n\n不过需要确认一下",
        "\n\n另外，不要编造代码",
        "\n\n不过总结一下",
        "\n\n哦，对了",
        "\n\n哦对了",
        "\n\n不过还要注意",
        "不过现在，按照系统提示",
        "另外，有没有需要调用工具",
        "不过有没有需要调用工具",
        "有没有需要调用工具",
        "这样就可以了",
        "不过等一下",
        "那现在按照要求",
        "不过需要确认一下",
        "另外，不要编造代码",
        "不过总结一下",
        "哦，对了",
        "哦对了",
        "不过还要注意",
    )
    trimmed = text.strip()
    cut_at = len(trimmed)
    for marker in markers:
        index = trimmed.find(marker)
        if index >= 20:
            cut_at = min(cut_at, index)
    return trimmed[:cut_at].strip()


def _trim_repeated_answer_block(text: str) -> str:
    anchors = (
        "你可以直接查看项目根目录",
        "如果需要快速上手",
        "基础使用步骤",
        "基础快速使用步骤",
        "快速入门的最简示例流程",
        "快速入门的最简标准流程",
        "安装依赖：执行",
        "你可以按照以下步骤使用FastAPI",
        "你可以通过以下方式学习和使用",
        "你可以先查看这个本地FastAPI仓库",
        "该FastAPI项目主要",
        "该项目主要",
    )
    trimmed = text.strip()
    for anchor in anchors:
        first = trimmed.find(anchor)
        if first < 0:
            continue
        second = trimmed.find(anchor, first + len(anchor))
        if second > 0:
            trimmed = trimmed[:second].strip()
    return trimmed


async def stream_answer(project: Project, question: str) -> AsyncIterator[str]:
    root = Path(project.local_path)
    llm = get_openai_compatible_chat()
    yield _sse("status", {"message": "已收到问题，正在准备源码工具"})

    if is_ark_enabled():
        system_prompt = """你是 Project Helper 的源码导师。你会基于提供的源码文件列表和搜索命中回答问题。
要求：
- 用中文回答，解释要通俗。
- 涉及代码时给出相对路径、函数名或关键行线索。
- 如果上下文证据不足，明确说还需要查看哪些文件。
- 不要编造不存在的文件或实现。
- 只输出最终答案，不要输出思考过程、自我纠错过程或草稿。
"""
        user_prompt = f"{_question_context(project, question)}\n用户问题：{question}"
        try:
            yield _sse("status", {"message": "正在调用火山方舟模型"})
            chunks: list[str] = []
            for chunk in stream_text(system_prompt, user_prompt):
                chunks.append(chunk)
            answer = _clean_answer("".join(chunks), question)
            if _is_usage_question(question) and _looks_like_internal_answer(answer):
                answer = _usage_answer(project)
            if answer:
                yield _sse("delta", {"content": answer})
            else:
                yield _sse("delta", {"content": "火山方舟没有返回文本内容。"})
            yield _sse("done", {"message": "completed"})
            return
        except Exception as exc:
            fallback = _local_answer(project, question, reason="provider_error")
            yield _sse("error", {"message": f"火山方舟调用失败，已返回本地搜索结果：{exc}"})
            yield _sse("delta", {"content": fallback})
            yield _sse("done", {"message": "completed"})
            return

    if llm is None:
        yield _sse("delta", {"content": _local_answer(project, question)})
        yield _sse("done", {"message": "completed"})
        return

    def list_files(_: str = "") -> str:
        """List source files in the repository."""
        return "\n".join(path.relative_to(root).as_posix() for path in list(iter_source_files(root))[:120])

    def read_file(relative_path: str) -> str:
        """Read a repository file by relative path."""
        path = _safe_path(root, _clean_tool_input(relative_path))
        return safe_read(path, 24000)

    def search_code(pattern: str) -> str:
        """Search code with ripgrep-compatible text or regex pattern."""
        pattern = _clean_tool_input(pattern)
        try:
            result = subprocess.run(
                [
                    "rg",
                    "--line-number",
                    "--no-heading",
                    *_rg_ignore_args(),
                    pattern,
                    str(root),
                ],
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
        except Exception as exc:
            return f"Search failed: {exc}"
        lines = result.stdout.replace(str(root) + "/", "").splitlines()[:40]
        return "\n".join(lines) or "No matches."

    system_prompt = f"""你是 Project Helper 的源码导师。
仓库：{project.repo_url}
本地路径：{root}

回答规则：
- 必须先用工具查代码，不要凭空猜。
- 解释要通俗，适合刚接触项目的人。
- 涉及代码时给出相对路径和关键函数/类名。
- 如果证据不足，明确说还需要读哪些文件。
"""

    try:
        tools = [
            Tool.from_function(
                name="list_files",
                func=list_files,
                description="List repository source files. Input can be empty.",
            ),
            Tool.from_function(
                name="read_file",
                func=read_file,
                description="Read a repository file. Input must be a relative path, for example backend/app/main.py.",
            ),
            Tool.from_function(
                name="search_code",
                func=search_code,
                description="Search repository code with a text or regex pattern. Input is the pattern.",
            ),
        ]
        agent = initialize_agent(
            tools,
            llm,
            agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
            verbose=False,
            handle_parsing_errors=True,
            agent_kwargs={"prefix": system_prompt},
        )
        yield _sse("status", {"message": "Agent 正在搜索和读取源码"})
        answer = agent.run(question)
        yield _sse("delta", {"content": str(answer)})
        yield _sse("done", {"message": "completed"})
    except Exception as exc:
        fallback = _local_answer(project, question, reason="agent_error")
        yield _sse("error", {"message": f"AI Agent 调用失败，已返回本地搜索结果：{exc}"})
        yield _sse("delta", {"content": fallback})
        yield _sse("done", {"message": "completed"})
