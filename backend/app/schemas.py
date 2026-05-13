from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from pydantic import BaseModel, Field, HttpUrl


class AnalyzeRequest(BaseModel):
    repo_url: HttpUrl
    force: bool = False


class ProjectResponse(BaseModel):
    id: int
    repo_url: str
    repo_name: str
    status: str
    branch: str
    commit_sha: str
    report_markdown: str
    summary: Dict[str, Any]
    error_message: str
    created_at: datetime
    updated_at: datetime


class AnalyzeResponse(BaseModel):
    project: ProjectResponse
    cached: bool
    events_url: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
