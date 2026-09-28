from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Iterable

from .path_guard import PolicyError, resolve_under


class BuildTools:
    def __init__(
        self,
        workspace_root: str | Path,
        timeout_seconds: int = 600,
        allowed_targets: Iterable[str] = (),
    ):
        self.workspace_root = Path(workspace_root).expanduser().resolve(strict=True)
        self.timeout_seconds = timeout_seconds
        self.allowed_targets = {
            Path(value).as_posix().casefold() for value in allowed_targets if str(value).strip()
        }

    def _dotnet(self, params: dict[str, Any], verb: str) -> dict[str, Any]:
        target = resolve_under(self.workspace_root, str(params.get("solution", "")))
        if target.suffix.lower() not in {".sln", ".slnx", ".csproj"}:
            raise PolicyError("Build target must be a .sln, .slnx, or .csproj file")
        relative = target.relative_to(self.workspace_root).as_posix().casefold()
        if not self.allowed_targets or relative not in self.allowed_targets:
            raise PolicyError("Build target is not in the configured allowlist")
        configuration = str(params.get("configuration", "Debug"))
        if configuration not in {"Debug", "Release"}:
            raise PolicyError("configuration must be Debug or Release")
        completed = subprocess.run(
            ["dotnet", verb, str(target), "--configuration", configuration, "--nologo"],
            cwd=str(target.parent),
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-30000:],
            "stderr": completed.stderr[-10000:],
            "verb": verb,
            "target": str(target),
        }

    def build_solution(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self._dotnet(params, "build")

    def run_tests(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        return self._dotnet(params, "test")
