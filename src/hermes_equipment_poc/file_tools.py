from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .path_guard import PolicyError, reject_git_metadata, resolve_under


class FileTools:
    def __init__(self, workspace_root: str | Path, max_bytes: int = 2_000_000):
        self.workspace_root = Path(workspace_root).expanduser().resolve(strict=True)
        self.max_bytes = max_bytes

    def _path(self, raw: Any) -> Path:
        path = resolve_under(self.workspace_root, str(raw or ""))
        repo = self._find_repo(path)
        if repo is not None:
            reject_git_metadata(path, repo)
        return path

    @staticmethod
    def _find_repo(path: Path) -> Path | None:
        for parent in (path, *path.parents):
            if (parent / ".git").exists():
                return parent
        return None

    def read_workspace_file(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        path = self._path(params.get("path"))
        if not path.is_file():
            raise PolicyError(f"File does not exist: {path}")
        size = path.stat().st_size
        if size > self.max_bytes:
            raise PolicyError(f"File exceeds read limit: {size} bytes")
        data = path.read_bytes()
        if b"\x00" in data:
            raise PolicyError("Binary files are not supported")
        text = data.decode("utf-8-sig")
        return {
            "path": str(path),
            "content": text,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }

    def write_workspace_file(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        path = self._path(params.get("path"))
        content = str(params.get("content", ""))
        encoded = content.encode("utf-8")
        if len(encoded) > self.max_bytes:
            raise PolicyError(f"Content exceeds write limit: {len(encoded)} bytes")
        expected = str(params.get("expected_sha256", "")).strip().lower()
        if path.exists():
            current = hashlib.sha256(path.read_bytes()).hexdigest()
            if not expected:
                raise PolicyError("expected_sha256 is required when overwriting an existing file")
            if current != expected:
                raise PolicyError("File changed since it was read")
        elif expected:
            raise PolicyError("expected_sha256 was supplied for a new file")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encoded)
        return {
            "ok": True,
            "path": str(path),
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "bytes": len(encoded),
        }

    def search_log(self, params: dict[str, Any], **_: Any) -> dict[str, Any]:
        path = self._path(params.get("path"))
        pattern = str(params.get("pattern", "")).strip().casefold()
        if not pattern:
            raise ValueError("pattern is required")
        if path.suffix.lower() not in {".log", ".txt", ".csv", ".jsonl"}:
            raise PolicyError("Log search supports .log, .txt, .csv, and .jsonl only")
        limit = max(1, min(int(params.get("limit", 100)), 500))
        matches: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
            for number, line in enumerate(stream, 1):
                if pattern in line.casefold():
                    matches.append({"line": number, "text": line.rstrip("\r\n")[:4000]})
                    if len(matches) >= limit:
                        break
        return {"path": str(path), "matches": matches, "truncated": len(matches) >= limit}

