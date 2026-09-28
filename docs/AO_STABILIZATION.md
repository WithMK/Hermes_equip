# A/O milestones 1–3 stabilization

## Implemented safeguards

- Grounded output reserves square brackets for source citations. Extract every bracketed
  citation, reject unknown IDs and require a citation when evidence was supplied.
- Reject incomplete completion reasons such as `length`, `tool_calls` and `content_filter`.
  Empty finish reasons remain compatible with legacy endpoints; this cannot prove completeness.
- Use only complete evidence blocks within the character budget. Empty and oversized blocks
  are excluded before persistence and dispatch; if no usable evidence remains, return a safe
  no-evidence response. This trades recall for explicit, auditable evidence delivery.
- Specialist-local budgets are checked again before calling its provider. Validation uses only
  the actually rendered sources. Citation checks establish identity, not factual entailment.
- Specialist session keys hash Workspace, Task, caller session and Agent identity.
  Specialist API session forwarding remains opt-in; verify the actual Hermes session contract
  before setting `--specialist-session-field`. Direct user-to-C/M conversation continuity remains.
- Analysis agents do not receive unrelated previous specialist output. Synthesis roles receive
  earlier validated outputs. No dynamic agents or mutations are enabled.

## Explicit decision reuse

Pass `--decision-task-id TASK-ID` (repeatable, at most ten) to load saved decisions from completed
tasks in the same Workspace and Equipment. Only explicit decisions are inherited, never model
summaries. Existing request size limits still apply. No implicit global memory search is performed.

## Operator restart, not checkpoint continuation

Every new Task saves its normalized request before starting work. After stopping the original
worker, use the usual endpoint/workspace CLI options together with:

```powershell
--restart-task-id TASK-ID --expected-version 4 --confirm-worker-stopped
```

Read the current Task version from the State Store; `4` above is only an example.
Restart atomically marks an interrupted Task and running child Runs as failed, then uses the saved
request to create a NEW Task and repeat retrieval and read-only analysis. The new request snapshot
contains `restart_of`. Failed original Tasks remain immutable. Completed and waiting-approval Tasks
are rejected. A legacy Task without a request snapshot needs a new explicit request.

This is not automatic recovery, live takeover, or resumption at the last specialist. There is no
worker lease: operators MUST stop the original process first. Evidence is re-fetched rather than
reusing stale evidence. The old audit trail remains. No writes/builds/commits are replayed.

## Target-PC gates still open

1. Start actual pinned Hermes gateways and inspect exposed tools for every profile.
2. Confirm specialist authentication, HTTP completion schema and optional session behavior.
3. Verify Hermes -> C/M -> local LLM and A/O -> EquipmentRAG together, with C/M automatic RAG off.
4. Trigger timeout, truncated output, invalid citation, restart and cross-task session tests there.

Local automated tests use controlled providers; they do not certify these external services or
runtime tool isolation. Do not enable production write workflows until these gates pass.
