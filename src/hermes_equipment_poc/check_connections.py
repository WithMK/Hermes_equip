from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .http_client import JsonApiClient
from .service_clients import EquipmentRagClient


def _summary(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "service": name,
        "ok": True,
        "status": payload.get("status"),
        "result_count": payload.get("result_count"),
        "response_keys": sorted(payload),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate remote EquipmentRAG and ContextManager contracts")
    parser.add_argument("--equipment-rag-base-url", required=True)
    parser.add_argument("--context-manager-base-url")
    parser.add_argument("--query", default="Loader Vacuum Sensor")
    parser.add_argument("--context-health-path", default="/health")
    parser.add_argument("--context-chat-path", default="/v1/chat/completions")
    parser.add_argument("--context-model", default="REPLACE_MODEL_NAME")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args(argv)

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    def run(name: str, operation: Any) -> None:
        try:
            results.append(_summary(name, operation()))
        except Exception as exc:  # safe diagnostic boundary
            failures.append({"service": name, "error_type": type(exc).__name__, "error": str(exc)})

    rag = EquipmentRagClient(JsonApiClient(
        args.equipment_rag_base_url,
        os.environ.get("EQUIPMENT_RAG_API_KEY", ""),
        args.timeout_seconds,
    ))
    run("equipment_rag.health", rag.health)
    for source_type in ("code", "document", "all"):
        run(
            f"equipment_rag.retrieve.{source_type}",
            lambda value=source_type: rag.retrieve(
                query=args.query,
                source_type=value,
                top_k=3,
                include_content=False,
            ),
        )

    if args.context_manager_base_url:
        context = JsonApiClient(
            args.context_manager_base_url,
            os.environ.get("CONTEXT_MANAGER_API_KEY", ""),
            args.timeout_seconds,
        )
        run("context_manager.health", lambda: context.get(args.context_health_path))
        run(
            "context_manager.chat_completion",
            lambda: context.post(
                args.context_chat_path,
                {
                    "model": args.context_model,
                    "stream": False,
                    "temperature": 0,
                    "max_tokens": 16,
                    "messages": [
                        {"role": "user", "content": "Reply with exactly: HERMES_AO_OK"}
                    ],
                },
            ),
        )

    output = {"ok": not failures, "checks": results, "failures": failures}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
