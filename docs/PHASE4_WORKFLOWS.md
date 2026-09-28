# Phase 4A/4B: artifacts and uncommitted code proposals

## Boundary

Phase 4 does not authorize production deployment or a Git commit.

- **4A** converts a validated A/O result into an exclusive-create Markdown artifact, computes its
  SHA-256 and registers it on the Task before the Task becomes terminal.
- **4B** accepts a strict, operator-confirmed JSON proposal, starts from a clean `main`, creates a
  `work/ao-*` branch, compare-and-swap replaces explicitly allowlisted existing text files, runs an
  allowlisted .NET build/test, and writes the base comparison report outside the workspace.
- 4B never stages, commits, pushes, requests a merge or switches back to `main`.

The Hermes Code Development Agent remains read-only. It proposes the change and evidence; the
frontend/operator turns the confirmed change into the strict JSON input. The separate A/O Proposal
Workflow performs bounded mutation. This prevents the model-facing Agent from accessing commit or
merge tools.

## 4A report generation

Add the following options to `orchestrator_cli`:

```powershell
--create-artifact `
--artifact-root C:\ProgramData\HermesEquipment\artifacts
```

The artifact root should be outside source repositories and Agent-writeable workspaces. Each Task
has a hash-suffixed directory. The report path is exclusive-create, so retrying the same Task cannot
silently overwrite a prior report. The State Store records its path, type and SHA-256.

## 4B proposal JSON

Only complete replacement of existing UTF-8 text files is supported. New files, deletion, rename,
binary files and patches are intentionally excluded from this phase.

```json
{
  "repo": "TrimmerControl",
  "branch_name": "work/ao-task-e024-timeout",
  "build_target": "TrimmerControl/TrimmerControl.sln",
  "configuration": "Debug",
  "run_tests": true,
  "rationale": "Increase the bounded sensor confirmation timeout after review [S1]",
  "changes": [
    {
      "path": "Sequence/LoaderSequence.cs",
      "expected_sha256": "REPLACE_WITH_64_HEX_CURRENT_FILE_HASH",
      "content": "REPLACE_WITH_COMPLETE_NEW_UTF8_FILE_CONTENT"
    }
  ]
}
```

Unknown JSON fields and non-boolean `run_tests` values fail closed. `expected_sha256` is mandatory
and protects against overwriting code changed after the proposal was prepared.

## Execute for review

The operator must repeat every allowed file path and build target. Values inside the proposal do
not authorize themselves.

```powershell
py -m hermes_equipment_poc.proposal_cli `
  --state-db C:\ProgramData\HermesEquipment\state\orchestra.db `
  --workspace-root D:\EquipmentSW `
  --workspace-id trim-project `
  --artifact-root C:\ProgramData\HermesEquipment\artifacts `
  --objective "Loader timeout 변경 제안 비교" `
  --proposal-json C:\Review\TASK-E024-proposal.json `
  --allowed-change-path Sequence/LoaderSequence.cs `
  --allowed-build-target TrimmerControl/TrimmerControl.sln `
  --confirm-proposal-apply
```

Successful output has status `ready_for_review`, returns the diff, and leaves the repository on the
work branch with unstaged, uncommitted changes. The Markdown comparison artifact contains build and
test results, changed files, base SHA and diff. Checkpoints also store before/after file hashes.

If build/test or comparison fails, the Task is `failed`; when possible the comparison artifact is
still registered. The work branch and changes are deliberately preserved for diagnosis. The tool
does not automatically discard user or Agent changes. An operator must inspect and recover them.

## Runtime safety

- The base branch must be clean `main`; existing user edits stop execution before branch creation.
- The work branch must match `work/ao-*` and must not already exist.
- Changed and untracked paths after build must exactly match the proposal. Build-generated or
  unexpected files fail validation.
- HEAD must still equal the captured base SHA and the index must be empty. Any commit or staging
  attempt fails validation.
- File paths and build targets require separate operator allowlists.
- Artifact storage must be outside the workspace.
- A repository-specific external lock prevents concurrent Proposal Workflow runs. A process crash
  may leave a stale lock under `.proposal-locks`; an operator must verify no worker is active before
  removing it.

`dotnet build/test` can execute MSBuild targets. Run Hermes/A/O under an OS account without Git
push credentials, production credentials or equipment-network write access, and enforce outbound
network restrictions. Post-build checks can detect repository changes but cannot undo an external
side effect caused by a malicious build target.

## Not implemented

- autonomous conversion of free-form Agent text into an executable proposal
- new file creation, deletion or rename
- automatic rollback or branch cleanup
- staging, commit, push, pull request, merge request or `main` update
- production deployment or equipment control
