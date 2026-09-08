from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from hermes_equipment_poc.audit import AuditWriter
from hermes_equipment_poc.build_tools import BuildTools
from hermes_equipment_poc.file_tools import FileTools
from hermes_equipment_poc.git_tools import GitTools
from hermes_equipment_poc.merge_broker import MergeApprovalBroker
from hermes_equipment_poc.path_guard import PolicyError, resolve_under
from hermes_equipment_poc.plugin import register


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, capture_output=True)
    return result.stdout.strip()


class FakeContext:
    def __init__(self, base: Path):
        self.root = base / "workspace"
        self.root.mkdir()
        self.approval_store = base / "approvals"
        self.profile_name = "test-agent"
        self.tools: dict[str, dict] = {}
        self.hooks: dict[str, object] = {}

    def get_config(self, key: str, default=None):
        if key == "workspace_root":
            return str(self.root)
        if key == "git.approval_store":
            return str(self.approval_store)
        return default

    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs

    def register_hook(self, name, callback):
        self.hooks[name] = callback


class PathPolicyTests(unittest.TestCase):
    def test_outside_workspace_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(PolicyError):
                resolve_under(root, root.parent / "escape.txt")


class PluginSurfaceTests(unittest.TestCase):
    def test_surface_has_no_terminal_motion_or_force_push_tool(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = FakeContext(Path(temp))
            register(ctx)
            names = set(ctx.tools)
            self.assertIn("request_main_merge", names)
            for forbidden in ("terminal", "run_command", "force_push", "plc_write", "servo_on", "motion_move"):
                self.assertNotIn(forbidden, names)

    def test_main_merge_executor_is_not_exposed_as_tool(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = FakeContext(Path(temp))
            register(ctx)
            self.assertIn("request_main_merge", ctx.tools)
            self.assertNotIn("execute_main_merge", ctx.tools)
            self.assertNotIn("_execute_main_merge", ctx.tools)
            self.assertIsNone(ctx.hooks["pre_tool_call"]("request_main_merge", {}, session_id="s1"))


class FilePolicyTests(unittest.TestCase):
    def test_existing_file_requires_compare_and_swap_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "a.cs"
            path.write_text("old", encoding="utf-8")
            tools = FileTools(root)
            with self.assertRaises(PolicyError):
                tools.write_workspace_file({"path": "a.cs", "content": "new"})
            read = tools.read_workspace_file({"path": "a.cs"})
            result = tools.write_workspace_file({"path": "a.cs", "content": "new", "expected_sha256": read["sha256"]})
            self.assertTrue(result["ok"])


class BuildPolicyTests(unittest.TestCase):
    def test_build_target_must_be_explicitly_allowlisted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "Equipment.sln"
            target.write_text("", encoding="utf-8")
            tools = BuildTools(root)
            with self.assertRaises(PolicyError):
                tools.build_solution({"solution": "Equipment.sln"})


class GitPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "PoC Test")
        git(self.repo, "config", "user.email", "poc@example.invalid")
        (self.repo / "file.txt").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", "file.txt")
        git(self.repo, "commit", "-m", "initial")
        self.tools = GitTools(self.workspace)
        self.broker = MergeApprovalBroker(self.root / "approvals", self.tools)

    def tearDown(self):
        self.temp.cleanup()

    def test_direct_main_commit_is_rejected(self):
        (self.repo / "file.txt").write_text("changed\n", encoding="utf-8")
        git(self.repo, "add", "file.txt")
        with self.assertRaises(PolicyError):
            self.tools.commit_work_branch({"repo": "repo", "message": "forbidden commit"})

    def test_work_branch_commit_and_exact_sha_merge(self):
        self.tools.create_branch({"repo": "repo", "name": "work/change"})
        (self.repo / "file.txt").write_text("changed\n", encoding="utf-8")
        self.tools.stage_files({"repo": "repo", "paths": ["file.txt"]})
        commit = self.tools.commit_work_branch({"repo": "repo", "message": "Apply safe change"})
        sha = commit["commit"]
        request = self.broker.request({"repo": "repo", "source_branch": "work/change", "expected_sha": sha})
        self.assertFalse(request["executed"])
        self.assertEqual("work/change", git(self.repo, "branch", "--show-current"))
        result = self.broker.approve_and_execute(request["request_id"])
        self.assertEqual("main", result["target_branch"])
        self.assertEqual(sha, result["source_sha"])
        with self.assertRaises(PolicyError):
            self.broker.approve_and_execute(request["request_id"])

    def test_merge_rejects_changed_or_wrong_sha(self):
        self.tools.create_branch({"repo": "repo", "name": "work/change"})
        with self.assertRaises(PolicyError):
            self.broker.request({"repo": "repo", "source_branch": "work/change", "expected_sha": "0" * 40})


class AuditTests(unittest.TestCase):
    def test_audit_is_jsonl_with_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "audit.jsonl"
            writer = AuditWriter(path, "agent-a")
            writer.post_tool_call("search_code", {"query": "x"}, '{"ok":true}', session_id="s1", duration_ms=2, status="success")
            row = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("agent-a", row["agent_id"])
            self.assertEqual("s1", row["session_id"])
            self.assertEqual("search_code", row["tool_name"])


if __name__ == "__main__":
    unittest.main()
