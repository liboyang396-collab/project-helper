from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Project
from app.services.events import add_event, set_project_status
from app.services.llm import invoke_text
from app.services.source_scan import grep, safe_read, scan_repository


def _bullet_list(items: list[str] | list[tuple[str, int]], empty: str = "暂未识别") -> str:
    if not items:
        return f"- {empty}"
    lines = []
    for item in items:
        if isinstance(item, tuple):
            lines.append(f"- `{item[0]}`：{item[1]} 个文件")
        else:
            lines.append(f"- `{item}`")
    return "\n".join(lines)


def _readme_excerpt(root: Path) -> str:
    for name in ("README.md", "readme.md", "README.MD"):
        path = root / name
        if path.exists():
            text = safe_read(path, 5000).strip()
            return text[:2500]
    return ""


def _infer_design_patterns(root: Path) -> list[str]:
    probes = {
        "依赖注入 / 服务层": r"Depends\(|inject|container|service",
        "MVC / 路由控制器": r"controller|router|views?|routes?",
        "Repository 数据访问层": r"repository|dao|mapper",
        "组件化 UI": r"components?|props|emit|slots",
        "状态管理": r"store|pinia|redux|zustand|vuex",
        "中间件 / 拦截器": r"middleware|interceptor|hook",
        "事件驱动": r"event|emit|listener|subscribe|pubsub",
    }
    found = []
    for label, pattern in probes.items():
        if grep(root, pattern, limit=3):
            found.append(label)
    return found


def _build_local_report(project: Project, summary: dict, root: Path) -> str:
    package = summary.get("package") or {}
    readme = _readme_excerpt(root)
    patterns = _infer_design_patterns(root)
    api_hits = grep(root, r"FastAPI|APIRouter|express\(|router\.|@app\.|fetch\(|axios|useQuery", limit=18)
    db_hits = grep(root, r"sqlite|postgres|mysql|redis|prisma|sqlalchemy|mongoose|typeorm|knex", limit=18)

    scripts = package.get("scripts") or {}
    scripts_md = "\n".join(f"- `{name}`：`{cmd}`" for name, cmd in scripts.items()) or "- 未发现 package.json scripts"

    return f"""# {project.repo_name} 源码学习报告

## 1. 项目概述

- 仓库：`{project.repo_url}`
- 当前提交：`{project.commit_sha[:12] or "未知"}`
- 可读源码文件数：{summary.get("file_count", 0)}
- 主要入口：{", ".join(f"`{item}`" for item in summary.get("entrypoints", [])) or "暂未自动识别"}

{readme[:1200] if readme else "这个仓库没有明显的 README，下面的理解主要来自源码结构和配置文件。"}

## 2. 技术栈

{_bullet_list(summary.get("tech_stack", []))}

### 依赖与脚本

{scripts_md}

## 3. 目录结构

```text
{summary.get("tree", "")}
```

## 4. 核心目录与模块

{_bullet_list(summary.get("top_dirs", []), "项目文件较少或主要集中在根目录")}

重点配置/说明文件：

{_bullet_list(summary.get("important_files", [])[:20])}

## 5. 数据流与调用链

从静态扫描看，可以按这条路线理解项目：

1. 先看入口文件，确认应用如何启动、路由如何挂载、全局配置在哪里初始化。
2. 再看路由/页面层，它们通常负责接收用户输入、调用服务模块、返回响应或渲染状态。
3. 接着看 service/store/model/repository 这类目录，它们承载业务逻辑、状态管理和数据访问。
4. 最后看配置文件和构建脚本，确认环境变量、依赖版本、启动命令和部署方式。

可能的 API / 前后端交互线索：

```text
{api_hits or "暂未搜索到明显 API 调用线索"}
```

可能的数据存储线索：

```text
{db_hits or "暂未搜索到明显数据库或缓存线索"}
```

## 6. 设计模式与工程习惯

{_bullet_list(patterns, "未从关键词中识别到稳定模式，建议结合入口和核心目录继续阅读")}

## 7. 傻瓜式阅读路线

1. 先读 `README` 和配置文件，只搞清楚“它是什么、怎么跑起来”。
2. 找入口文件，不要急着钻细节，只画出启动流程。
3. 按用户动作追代码：页面按钮/接口请求 -> 路由/控制器 -> 服务函数 -> 数据层。
4. 每次只追一个功能，读完就用自己的话写一句“这个功能把什么输入变成什么输出”。
5. 遇到看不懂的函数，先问问答 Agent：“这个函数被谁调用？它改变了什么数据？”

## 8. 下一步建议

- 从这些入口开始：{", ".join(f"`{item}`" for item in summary.get("entrypoints", [])[:8]) or "`README`、配置文件、路由目录"}
- 搜索关键词：`main`、`router`、`service`、`store`、`model`、`config`
- 如果要改功能，先让问答 Agent 查“相关文件有哪些”，再让它解释调用链。
"""


def _enhance_report_with_llm(local_report: str, summary: dict) -> str:
    prompt = f"""
你是项目学习助手。请基于下面的静态扫描报告，重写成一份更通俗、更完整的中文源码学习报告。

要求：
- 面向新手，语言直白，不要假装读过不存在的信息。
- 保留这些章节：项目概述、技术栈、目录结构、核心模块、数据流、设计模式、阅读建议。
- 对不确定的地方明确说“从静态扫描推测”。
- 输出 Markdown。

静态扫描摘要 JSON：
```json
{json.dumps(summary, ensure_ascii=False)[:12000]}
```

初始报告：
{local_report[:18000]}
"""
    try:
        content = invoke_text("你擅长把复杂源码讲给零基础开发者听。", prompt)
        return content or local_report
    except Exception as exc:
        return local_report + f"\n\n> AI 增强报告生成失败，已保留本地静态分析结果：`{exc}`\n"


def analyze_project(db: Session, project_id: int) -> None:
    project = db.get(Project, project_id)
    if project is None:
        return

    try:
        set_project_status(db, project, "analyzing")
        add_event(db, project.id, "scan", "正在扫描目录、识别语言和入口文件", 35)

        root = Path(project.local_path)
        summary = scan_repository(root)

        add_event(db, project.id, "report", "正在生成通俗源码分析报告", 65)
        local_report = _build_local_report(project, summary, root)
        report = _enhance_report_with_llm(local_report, summary)

        project.summary_json = json.dumps(summary, ensure_ascii=False)
        project.report_markdown = report
        project.status = "completed"
        db.add(project)
        db.commit()
        add_event(db, project.id, "done", "分析完成，报告已缓存", 100)
    except Exception as exc:
        project = db.get(Project, project_id)
        if project is not None:
            set_project_status(db, project, "failed", str(exc))
            add_event(db, project.id, "failed", f"分析失败：{exc}", 100)
