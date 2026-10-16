"""Project Agent configuration and current validation state."""
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .agent_manager import AgentConflict
from .projects import ProjectConflict, ProjectMissing


class Assignment(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    agent_id: str = Field(pattern=r'^[a-z0-9][a-z0-9_-]{0,63}$')
    assignment: str = Field(default='', max_length=120)
    instructions: str = Field(default='', max_length=4000)
    enabled: bool = True
    allow_delegation: bool = True


class AssignmentConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: int = Field(default=1, ge=1, le=1)
    mode: Literal['legacy', 'custom'] = 'legacy'
    default_agent_id: str = Field(default='', max_length=64)
    agents: list[Assignment] = Field(default_factory=list, max_length=32)
    delegation_enabled: bool = True
    max_delegations: int = Field(default=4, ge=0, le=8)


class SaveAssignments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    version: int = Field(ge=0)
    configuration: AssignmentConfiguration


def assignment_issues(configuration, profiles):
    issues, seen = [], set()
    by_id = {p['agent_id']: p for p in profiles}
    active, roles = set(), set()
    for item in configuration['agents']:
        identity = item['agent_id']
        if identity in seen:
            issues.append(f'Duplicate Agent: {identity}')
        seen.add(identity)
        profile = by_id.get(identity)
        if profile is None:
            issues.append(f'Agent not found: {identity}')
        elif not profile['available']:
            issues.append(f'Agent role unavailable: {identity}')
        elif item['enabled']:
            if not profile['enabled']:
                issues.append(f'Agent is disabled: {identity}')
            else:
                active.add(identity)
                if profile['role'] in roles:
                    issues.append('Only one enabled assignment per specialist role is supported')
                roles.add(profile['role'])
    default = configuration['default_agent_id']
    if default and default not in active:
        issues.append('Default Agent must be an enabled assignment with an active profile')
    if configuration['mode'] == 'custom' and not default:
        issues.append('Custom configuration requires a default Agent')
    if configuration['delegation_enabled'] and configuration['max_delegations'] == 0:
        issues.append('Enabled delegation requires a positive limit')
    return issues


def install_project_agent_routes(app, worker, manager, *, execution_enabled=True):
    def perform(action):
        try:
            return action()
        except ProjectMissing as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ProjectConflict, AgentConflict) as exc:
            raise HTTPException(409, str(exc)) from exc

    def present(data):
        profiles = manager.list() if manager else []
        issues = assignment_issues(data['configuration'], profiles)
        custom = data['configuration']['mode'] == 'custom'
        if custom and manager is None:
            issues.append('Agent management is not configured')
        if custom and not execution_enabled:
            issues.append('전문 Agent 실행이 꺼져 있습니다. 서버의 --enable-specialists 설정을 확인하세요.')
        return {**data, 'runtime_applied': custom and not issues, 'execution_mode': 'project' if custom else 'legacy',
                'validation_issues': issues}

    @app.get('/v1/projects/{project_id}/agent-assignments')
    def get_assignments(project_id: str):
        return perform(lambda: present(worker.projects.agent_assignments(project_id)))

    @app.put('/v1/projects/{project_id}/agent-assignments')
    def save_assignments(project_id: str, value: SaveAssignments):
        def action():
            worker.projects.get(project_id)
            if manager is None:
                raise HTTPException(503, 'Agent management is not configured')
            # Registry edits/tests/execution and this validation/save cannot interleave.
            with manager.exclusive():
                configuration = value.configuration.model_dump()
                if configuration['mode'] == 'custom' and not execution_enabled:
                    raise HTTPException(409, '프로젝트 배정 실행에는 서버의 --enable-specialists 설정이 필요합니다.')
                issues = assignment_issues(configuration, manager.list())
                if issues:
                    raise HTTPException(422, {'message': 'Invalid Agent assignments', 'issues': issues})
                return present(worker.projects.save_agent_assignments(project_id, value.version, configuration))
        return perform(action)
