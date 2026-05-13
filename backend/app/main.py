from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Dict, List

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, SessionLocal, engine, get_db
from app.models import AnalysisEvent, Project
from app.schemas import AnalyzeRequest, AnalyzeResponse, ChatRequest, ProjectResponse
from app.services.analyzer import analyze_project
from app.services.events import add_event, set_project_status
from app.services.qa_agent import stream_answer
from app.services.repository import clone_or_refresh, normalize_repo_url, repo_slug, storage_path_for


settings = get_settings()
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def project_to_response(project: Project) -> ProjectResponse:
    try:
        summary = json.loads(project.summary_json or "{}")
    except json.JSONDecodeError:
        summary = {}
    return ProjectResponse(
        id=project.id,
        repo_url=project.repo_url,
        repo_name=project.repo_name,
        status=project.status,
        branch=project.branch,
        commit_sha=project.commit_sha,
        report_markdown=project.report_markdown,
        summary=summary,
        error_message=project.error_message,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def run_analysis_job(project_id: int, repo_url: str, force: bool) -> None:
    db = SessionLocal()
    project = db.get(Project, project_id)
    if project is None:
        db.close()
        return

    try:
        set_project_status(db, project, "cloning")
        add_event(db, project.id, "clone", "正在克隆或刷新 GitHub 仓库", 10)
        local_path, branch, commit_sha = clone_or_refresh(repo_url, force=force)

        project.local_path = str(local_path)
        project.branch = branch
        project.commit_sha = commit_sha
        db.add(project)
        db.commit()
        add_event(db, project.id, "clone", f"仓库就绪：{commit_sha[:12]}", 25)
        analyze_project(db, project.id)
    except Exception as exc:
        project = db.get(Project, project_id)
        if project is not None:
            set_project_status(db, project, "failed", str(exc))
            add_event(db, project.id, "failed", f"任务失败：{exc}", 100)
    finally:
        db.close()


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/projects", response_model=List[ProjectResponse])
def list_projects(db: Session = Depends(get_db)) -> List[ProjectResponse]:
    projects = db.scalars(select(Project).order_by(Project.updated_at.desc()).limit(30)).all()
    return [project_to_response(project) for project in projects]


@app.get("/api/projects/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db)) -> ProjectResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project_to_response(project)


@app.post("/api/projects/analyze", response_model=AnalyzeResponse)
def analyze(
    payload: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> AnalyzeResponse:
    try:
        repo_url = normalize_repo_url(str(payload.repo_url))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    existing = db.scalar(select(Project).where(Project.repo_url == repo_url))
    if existing and existing.status == "completed" and not payload.force:
        return AnalyzeResponse(
            project=project_to_response(existing),
            cached=True,
            events_url=f"/api/projects/{existing.id}/events",
        )

    if existing is None:
        project = Project(
            repo_url=repo_url,
            repo_name=repo_slug(repo_url),
            local_path=str(storage_path_for(repo_url)),
            status="pending",
        )
        db.add(project)
        db.commit()
        db.refresh(project)
    else:
        project = existing
        project.status = "pending"
        project.report_markdown = "" if payload.force else project.report_markdown
        project.error_message = ""
        if payload.force:
            db.query(AnalysisEvent).filter(AnalysisEvent.project_id == project.id).delete()
        db.add(project)
        db.commit()
        db.refresh(project)

    add_event(db, project.id, "queued", "任务已加入分析队列", 1)
    background_tasks.add_task(run_analysis_job, project.id, repo_url, payload.force)
    return AnalyzeResponse(
        project=project_to_response(project),
        cached=False,
        events_url=f"/api/projects/{project.id}/events",
    )


@app.get("/api/projects/{project_id}/events")
async def project_events(project_id: int) -> StreamingResponse:
    async def event_generator():
        last_id = 0
        while True:
            db = SessionLocal()
            project = db.get(Project, project_id)
            if project is None:
                db.close()
                yield "event: error\ndata: {\"message\":\"Project not found\"}\n\n"
                return

            events = db.scalars(
                select(AnalysisEvent)
                .where(AnalysisEvent.project_id == project_id, AnalysisEvent.id > last_id)
                .order_by(AnalysisEvent.id)
            ).all()
            for event in events:
                last_id = event.id
                data = {
                    "id": event.id,
                    "stage": event.stage,
                    "message": event.message,
                    "progress": event.progress,
                    "created_at": event.created_at.isoformat(),
                }
                yield f"event: progress\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

            status = project.status
            db.close()
            if status in {"completed", "failed"} and not events:
                yield f"event: {status}\ndata: {{\"status\":\"{status}\"}}\n\n"
                return
            await asyncio.sleep(0.8)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/projects/{project_id}/chat/stream")
async def chat_stream(project_id: int, payload: ChatRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status != "completed":
        raise HTTPException(status_code=409, detail="Project analysis is not completed")
    if not Path(project.local_path).exists():
        raise HTTPException(status_code=404, detail="Repository files are missing")

    return StreamingResponse(
        stream_answer(project, payload.question),
        media_type="text/event-stream",
    )
