# Agent Orchestra Development Plan

## Boundary

- ContextManager: bounded conversation, summary, token budget, `/v1/chat/completions` proxy
- EquipmentRAG: explicit code/document evidence retrieval
- Agent Orchestra: Project/Equipment/Task state, planning, delegation, validation and artifacts
- Hermes: runtime, skills, tool dispatch and approval transport

## Milestones

1. Foundation: correct service boundaries, CI and domain contracts.
2. State Store: SQLite persistence for Task, Run, Evidence, Artifact and Checkpoint.
3. Single Orchestrator: classify, plan, retrieve, call C/M, validate and persist.
4. Specialist delegation: document, code analysis, troubleshooting and code development.
5. Production workflows: reports, code change, build/test, commit and merge request.
6. Closed-network acceptance: clean offline install, recovery and negative security tests.

## Initial constraints

- Sequential delegation only.
- No dynamic agent creation or free-form P2P messaging.
- No arbitrary terminal, equipment control or production deployment.
- No direct main commit, force push or Agent-executed main merge.
- LangGraph is deferred until native Hermes delegation proves insufficient.

## First acceptance scenario

> Analyze repeated E-024 Loader Vacuum alarms using related documents and code, then create a
> Markdown report containing root-cause candidates, verification order, actions and evidence IDs.

The milestone passes when the Task reaches `completed`, every factual claim is traceable to an
EquipmentRAG source, the report is registered as an artifact, and the audit log records every Tool
call without exposing credentials.
