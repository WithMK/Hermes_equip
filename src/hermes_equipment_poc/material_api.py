"""Project-scoped upload proxy. Document bytes and indexing live in the RAG service."""
import base64
import binascii
import re
from pathlib import PurePath

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .http_client import AdapterError
from .projects import ProjectConflict, ProjectMissing

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_BODY_BYTES = 14 * 1024 * 1024


class Upload(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    filename: str = Field(min_length=1, max_length=180)
    content_base64: str = Field(min_length=1, max_length=MAX_BODY_BYTES)
    version: int = Field(default=0, ge=0)


class Retry(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: int = Field(ge=1)


def install_material_routes(app, worker, client):
    def perform(action):
        if client is None:
            raise HTTPException(503, '자료 등록 연결이 설정되지 않았습니다.')
        try:
            return action()
        except ProjectMissing as exc:
            raise HTTPException(404, str(exc)) from exc
        except ProjectConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except AdapterError as exc:
            # Never expose upstream URLs, paths, credentials or raw error bodies.
            cause = exc.__cause__
            status = getattr(cause, 'code', 502)
            if status == 409:
                raise HTTPException(409, '자료가 변경되었거나 처리 중입니다. 새로고침 후 다시 시도하세요.') from exc
            if status in {413, 422}:
                raise HTTPException(status, '파일 형식·이름·크기를 확인하세요. 파일당 최대 10 MiB입니다.') from exc
            raise HTTPException(502, 'RAG 자료 서비스 연결·인증을 확인하세요. 접수 여부는 목록 새로고침으로 확인할 수 있습니다.') from exc

    def path(project):
        return f"/v1/ingestion/{project['materials_namespace']}/documents"

    @app.get('/v1/projects/{project_id}/materials')
    def list_materials(project_id: str):
        def action():
            project = worker.projects.get(project_id)
            if not project.get('materials_namespace'):
                return {'documents': []}
            return client.get(path(project))
        return perform(action)

    @app.post('/v1/projects/{project_id}/materials', status_code=202)
    def upload(project_id: str, value: Upload):
        if re.search(r'[\\/:*?"<>|\x00-\x1f]', value.filename) or PurePath(value.filename).suffix.lower() not in {'.md', '.txt', '.pdf', '.docx', '.pptx', '.xlsx'}:
            raise HTTPException(422, '지원 형식: MD, TXT, PDF, DOCX, PPTX, XLSX. 파일 이름에 경로를 포함할 수 없습니다.')
        try:
            content = base64.b64decode(value.content_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(422, '파일 전송 형식이 잘못되었습니다.') from exc
        if not content or len(content) > MAX_FILE_BYTES:
            raise HTTPException(413, '파일 크기는 1 byte ~ 10 MiB여야 합니다.')
        def action():
            project = worker.projects.bind_materials(project_id)
            equipment = project['subject_id'] if project['domain_id'] == 'equipment' else ''
            return client.post(path(project), {**value.model_dump(), 'project': project['knowledge_project'], 'equipment': equipment})
        return perform(action)

    @app.post('/v1/projects/{project_id}/materials/{document_id}/retry', status_code=202)
    def retry(project_id: str, document_id: str, value: Retry):
        if not re.fullmatch(r'[a-f0-9]{64}', document_id):
            raise HTTPException(404, '자료를 찾을 수 없습니다.')
        def action():
            project = worker.projects.get(project_id)
            if project['status'] != 'active' or not project.get('materials_namespace'):
                raise ProjectConflict('활성 프로젝트의 등록 자료만 재시도할 수 있습니다.')
            return client.post(path(project) + '/' + document_id + '/retry', value.model_dump())
        return perform(action)
