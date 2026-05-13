from sqlalchemy.orm import Session

from app.models import AnalysisEvent, Project


def add_event(db: Session, project_id: int, stage: str, message: str, progress: int) -> AnalysisEvent:
    event = AnalysisEvent(project_id=project_id, stage=stage, message=message, progress=progress)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def set_project_status(db: Session, project: Project, status: str, error_message: str = "") -> None:
    project.status = status
    project.error_message = error_message
    db.add(project)
    db.commit()
