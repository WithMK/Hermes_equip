"""Same-origin project administration; requests never choose paths or service URLs."""
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .projects import ProjectConflict, ProjectMissing


class ProjectFields(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=2000)
    subject_id: str = Field(default='', max_length=200)
    knowledge_project: str = Field(default='', max_length=200)
    repository: str = Field(default='', max_length=200)


class NewProject(ProjectFields):
    project_id: str = Field(min_length=1, max_length=64)


class UpdateProject(ProjectFields):
    version: int = Field(ge=1)
    status: Literal['active', 'archived'] = 'active'


class MemoryNote(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['decision', 'open_item']
    content: str = Field(min_length=1, max_length=1000)
    source_task_id: str = Field(default='', max_length=200)


class UpdateNote(MemoryNote):
    version: int = Field(ge=1)
    status: Literal['active', 'resolved'] = 'active'


def install_project_routes(app, worker):
    def perform(action):
        try:
            return action()
        except ProjectMissing as exc:
            raise HTTPException(404, str(exc)) from exc
        except ProjectConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def save(project_id, value, note_id=''):
        if value.source_task_id:
            worker.source_job(project_id, value.source_task_id)
        return worker.projects.save_note(project_id, **value.model_dump(), note_id=note_id)

    @app.get('/v1/projects')
    def list_projects():
        return worker.projects.list()

    @app.post('/v1/projects', status_code=201)
    def create_project(value: NewProject):
        return perform(lambda: worker.projects.create(**value.model_dump()))

    @app.get('/v1/projects/{project_id}')
    def get_project(project_id: str):
        return perform(lambda: worker.projects.get(project_id))

    @app.put('/v1/projects/{project_id}')
    def update_project(project_id: str, value: UpdateProject):
        return perform(lambda: worker.projects.update(project_id, **value.model_dump()))

    @app.get('/v1/projects/{project_id}/memory')
    def notes(project_id: str):
        return perform(lambda: worker.projects.notes(project_id))

    @app.post('/v1/projects/{project_id}/memory', status_code=201)
    def add_note(project_id: str, value: MemoryNote):
        return perform(lambda: save(project_id, value))

    @app.put('/v1/projects/{project_id}/memory/{note_id}')
    def update_note(project_id: str, note_id: str, value: UpdateNote):
        return perform(lambda: save(project_id, value, note_id))

    @app.get('/v1/projects/{project_id}/history')
    def history(project_id: str):
        return perform(lambda: worker.projects.history(project_id))
