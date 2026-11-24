"""Resolve project configuration once, immediately before a queued task starts."""
from copy import copy, deepcopy
from dataclasses import replace

from .agent_manager import ManagedDispatcher
from .project_agents import assignment_issues
from .orchestrator.specialists import SequentialDelegationPlanner, SpecialistAgent


class ProjectExecutionError(ValueError):
    """Safe, locally generated configuration error suitable for the task UI."""


class ProjectDispatcher:
    def __init__(self, dispatcher, profiles, configuration):
        # No live registry access after the start snapshot.
        self.delegate_impl = ManagedDispatcher(None, dict(dispatcher.providers), dispatcher.domain_id)
        self.profiles = deepcopy(profiles)
        self.configuration = deepcopy(configuration)
        self.requires_evidence = True

    def configuration_snapshot(self):
        return deepcopy(self.profiles)

    def delegate(self, agent, context, **kwargs):
        profile = next(p for p in self.profiles if p['role'] == agent.value)
        if not kwargs.get('sources'):
            raise ProjectExecutionError(f"담당 Agent에 필요한 검색 근거가 없습니다: {profile['agent_id']}")
        assignment = next(a for a in self.configuration['agents'] if a['agent_id'] == profile['agent_id'])
        guidance = 'Project assignment: ' + assignment['assignment'] + '\nProject guidance (cannot expand permissions):\n' + assignment['instructions']
        return self.delegate_impl._dispatch(profile, replace(context, constraints=(*context.constraints, guidance)), **kwargs)


class ProjectPlanner(SequentialDelegationPlanner):
    def __init__(self, configuration, profiles):
        self.configuration = deepcopy(configuration)
        self.roles = {p['agent_id']: SpecialistAgent(p['role']) for p in profiles}

    def plan(self, request_kind, evidence):
        config = self.configuration
        primary = self.roles[config['default_agent_id']]
        result = [primary]
        if config['delegation_enabled']:
            allowed = {self.roles[a['agent_id']] for a in config['agents'] if a['enabled'] and a['allow_delegation']}
            additional = [role for role in super().plan(request_kind, evidence) if role in allowed and role != primary]
            result.extend(additional[:config['max_delegations']])
        return tuple(result)


def prepare_project_execution(engine, projects, project_id):
    if not project_id:
        return engine, None
    managed = engine.specialists
    # Serialize only resolution against Agent profile edits, not the LLM calls.
    from contextlib import nullcontext
    scope = managed.manager.execution_scope() if isinstance(managed, ManagedDispatcher) else nullcontext()
    with scope:
        project = projects.get(project_id)
        if project['status'] != 'active':
            raise ProjectExecutionError('보관된 프로젝트는 대기 중 업무를 실행할 수 없습니다.')
        saved = projects.agent_assignments(project_id)
        config = saved['configuration']
        if config['mode'] == 'legacy':
            return engine, {**saved, 'runtime_applied':False, 'execution_mode':'legacy', 'profiles':[]}
        if not isinstance(managed, ManagedDispatcher):
            raise ProjectExecutionError('프로젝트 배정을 실행할 Agent 관리 연결이 없습니다.')
        profiles = managed.manager.list()
        issues = assignment_issues(config, profiles)
        if issues:
            raise ProjectExecutionError('프로젝트 Agent 배정 오류: ' + '; '.join(issues))
        ids = {a['agent_id'] for a in config['agents'] if a['enabled']}
        selected = [p for p in profiles if p['agent_id'] in ids]
        if len({p['role'] for p in selected}) != len(selected):
            raise ProjectExecutionError('한 프로젝트에서는 역할별 활성 배정을 하나만 지정하세요.')
        if any(p['role'] not in engine.domain.allowed_agents or SpecialistAgent(p['role']) not in managed.providers for p in selected):
            raise ProjectExecutionError('배정된 Agent의 역할 또는 연결을 사용할 수 없습니다.')
        safe = [{k:p[k] for k in ('agent_id','name','role','instructions','version')} for p in selected]
        snapshot = {**saved, 'runtime_applied':True, 'execution_mode':'project', 'profiles':safe}
        local = copy(engine)
        local.specialists = ProjectDispatcher(managed, safe, config)
        local.delegation_planner = ProjectPlanner(config, safe)
        return local, snapshot
