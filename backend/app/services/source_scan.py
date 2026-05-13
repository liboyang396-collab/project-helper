from __future__ import annotations

import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".venv",
    "venv",
    "target",
    "coverage",
    ".firecrawl",
    "storage",
    ".pytest_cache",
}

TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".php",
    ".rb",
    ".cs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".css",
    ".scss",
    ".html",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".ini",
    ".env",
    ".sh",
    ".sql",
}

TECH_BY_FILE = {
    "package.json": "Node.js / 前端生态",
    "vite.config.ts": "Vite",
    "vite.config.js": "Vite",
    "next.config.js": "Next.js",
    "nuxt.config.ts": "Nuxt",
    "requirements.txt": "Python",
    "pyproject.toml": "Python",
    "poetry.lock": "Poetry",
    "Pipfile": "Pipenv",
    "go.mod": "Go",
    "Cargo.toml": "Rust",
    "pom.xml": "Maven / Java",
    "build.gradle": "Gradle / JVM",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    "compose.yml": "Docker Compose",
}

TECH_BY_EXTENSION = {
    ".py": "Python",
    ".vue": "Vue",
    ".ts": "TypeScript",
    ".tsx": "React / TypeScript",
    ".jsx": "React",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".php": "PHP",
    ".rb": "Ruby",
}


def iter_source_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if any(part in IGNORE_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS:
            yield path


def safe_read(path: Path, max_chars: int = 16000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
        return ""


def build_tree(root: Path, max_entries: int = 180) -> str:
    entries: list[str] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in IGNORE_DIRS for part in rel.parts):
            continue
        depth = len(rel.parts) - 1
        if depth > 3:
            continue
        prefix = "  " * depth + ("- " if path.is_file() else "+ ")
        entries.append(f"{prefix}{rel.name}")
        if len(entries) >= max_entries:
            entries.append("...")
            break
    return "\n".join(entries)


def scan_repository(root: Path) -> dict:
    files = list(iter_source_files(root))
    extension_counts = Counter(path.suffix.lower() or "[no ext]" for path in files)
    top_dirs: dict[str, int] = defaultdict(int)
    tech = set()
    important_files: list[str] = []
    entrypoints: list[str] = []
    config_files: list[str] = []

    for path in files:
        rel = path.relative_to(root).as_posix()
        parts = rel.split("/")
        if len(parts) > 1:
            top_dirs[parts[0]] += 1

        if path.name in TECH_BY_FILE:
            tech.add(TECH_BY_FILE[path.name])
            important_files.append(rel)
        if path.suffix.lower() in TECH_BY_EXTENSION:
            tech.add(TECH_BY_EXTENSION[path.suffix.lower()])
        if path.name.lower() in {"main.py", "app.py", "server.py", "index.js", "main.ts", "main.js", "app.vue"}:
            entrypoints.append(rel)
        if path.name.lower() in {
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "dockerfile",
            "docker-compose.yml",
            ".env.example",
            "vite.config.ts",
            "vite.config.js",
        }:
            config_files.append(rel)

    package_json = {}
    package_file = root / "package.json"
    if package_file.exists():
        try:
            package_json = json.loads(safe_read(package_file, 30000))
        except json.JSONDecodeError:
            package_json = {}

    return {
        "file_count": len(files),
        "extensions": extension_counts.most_common(12),
        "top_dirs": sorted(top_dirs.items(), key=lambda item: item[1], reverse=True)[:12],
        "tech_stack": sorted(tech),
        "important_files": important_files[:40],
        "entrypoints": entrypoints[:30],
        "config_files": config_files[:30],
        "tree": build_tree(root),
        "package": {
            "name": package_json.get("name"),
            "scripts": package_json.get("scripts", {}),
            "dependencies": sorted((package_json.get("dependencies") or {}).keys())[:60],
            "devDependencies": sorted((package_json.get("devDependencies") or {}).keys())[:60],
        },
    }


def grep(root: Path, pattern: str, limit: int = 30) -> str:
    glob_args = []
    for directory in IGNORE_DIRS:
        glob_args.extend(["--glob", f"!{directory}", "--glob", f"!**/{directory}/**"])
    try:
        result = subprocess.run(
            ["rg", "--line-number", "--no-heading", *glob_args, pattern, str(root)],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""

    lines = result.stdout.splitlines()[:limit]
    cleaned = []
    for line in lines:
        cleaned.append(line.replace(str(root) + "/", ""))
    return "\n".join(cleaned)
