from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

from app.config import get_settings


GITHUB_RE = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+/?$")


def normalize_repo_url(repo_url: str) -> str:
    url = repo_url.strip()
    if url.endswith(".git"):
        url = url[:-4]
    url = url.rstrip("/")
    if not GITHUB_RE.match(url):
        raise ValueError("Only public https://github.com/{owner}/{repo} repositories are supported.")
    return url


def repo_slug(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    parts = [part for part in parsed.path.split("/") if part]
    return "/".join(parts[:2])


def _repo_parts(repo_url: str) -> tuple[str, str]:
    owner, repo = repo_slug(repo_url).split("/", 1)
    return owner, repo


def storage_path_for(repo_url: str) -> Path:
    settings = get_settings()
    digest = hashlib.sha1(repo_url.encode("utf-8")).hexdigest()[:12]
    slug = repo_slug(repo_url).replace("/", "__")
    return settings.repo_storage_dir / f"{slug}__{digest}"


def _run_git(args: list[str], cwd: Path | None = None, timeout: int = 120) -> str:
    env = {
        **__import__("os").environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_HTTP_VERSION": "HTTP/1.1",
    }
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git command timed out after {timeout}s: git {' '.join(args)}") from exc
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "git command failed").strip())
    return result.stdout.strip()


def _http_json(url: str, timeout: int = 25) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "project-helper",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _download_file(url: str, target: Path, timeout: int = 90) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "project-helper"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with target.open("wb") as output:
            shutil.copyfileobj(response, output)


def _safe_extract_zip(zip_path: Path, target: Path) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        if not members:
            raise RuntimeError("Downloaded GitHub archive is empty.")
        top_level = members[0].filename.split("/", 1)[0]
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            archive.extractall(tmp_path)
            extracted_root = tmp_path / top_level
            if not extracted_root.exists():
                raise RuntimeError("Could not locate extracted GitHub archive root.")
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(extracted_root), str(target))


def _download_github_archive(repo_url: str, target: Path, original_error: Exception) -> tuple[str, str]:
    owner, repo = _repo_parts(repo_url)
    api_url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        metadata = _http_json(api_url)
        branch = metadata.get("default_branch") or "main"
        commit_sha = ""
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        branch = "main"
        commit_sha = ""
        metadata_error = exc
    else:
        metadata_error = None

    candidate_branches = [branch]
    for fallback in ("main", "master"):
        if fallback not in candidate_branches:
            candidate_branches.append(fallback)

    errors: list[str] = [f"git clone failed: {original_error}"]
    if metadata_error:
        errors.append(f"GitHub metadata lookup failed: {metadata_error}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        zip_path = Path(tmp_dir) / "repo.zip"
        for candidate in candidate_branches:
            archive_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{candidate}"
            try:
                _download_file(archive_url, zip_path)
                _safe_extract_zip(zip_path, target)
                return candidate, commit_sha or f"archive:{candidate}"
            except Exception as exc:
                errors.append(f"archive download failed for {candidate}: {exc}")

    raise RuntimeError("；".join(errors))


def clone_or_refresh(repo_url: str, force: bool = False) -> tuple[Path, str, str]:
    normalized = normalize_repo_url(repo_url)
    target = storage_path_for(normalized)
    settings = get_settings()
    settings.repo_storage_dir.mkdir(parents=True, exist_ok=True)

    if force and target.exists() and settings.repo_storage_dir.resolve() in target.resolve().parents:
        shutil.rmtree(target)

    if target.exists() and not (target / ".git").exists() and settings.repo_storage_dir.resolve() in target.resolve().parents:
        shutil.rmtree(target)

    if not target.exists():
        try:
            _run_git(
                ["clone", "--depth", "1", f"{normalized}.git", str(target)],
                timeout=get_settings().git_clone_timeout_seconds,
            )
        except Exception as exc:
            branch, commit_sha = _download_github_archive(normalized, target, exc)
            return target, branch, commit_sha
    else:
        if (target / ".git").exists():
            try:
                _run_git(["fetch", "--depth", "1", "origin"], cwd=target, timeout=60)
            except Exception:
                pass
        else:
            return target, "archive", "archive:cached"

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=target, timeout=10)
    commit_sha = _run_git(["rev-parse", "HEAD"], cwd=target, timeout=10)
    return target, branch, commit_sha
