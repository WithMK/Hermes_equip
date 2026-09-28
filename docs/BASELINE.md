# Hermes PoC Baseline

## Upstream pin

| Item | Value |
|---|---|
| Repository | `NousResearch/hermes-agent` |
| Tag | `v2026.9.7` |
| Commit | `2237be355906fbe6065ce1815711eee52b2d646e` |
| Verification date | 2026-09-08 |

PoC 결과는 반드시 이 태그를 기준으로 기록한다. `main`, `latest` 또는 날짜가 다른
설치본의 결과와 혼합하지 않는다.

## Verified source seams

- Agent loop: `agent/conversation_loop.py`, `agent/turn_*.py`
- Tool registry: `tools/registry.py`
- Plugin tools/hooks: `hermes_cli/plugins.py`
- Arbitrary tool approval: `tools/approval.py::request_tool_approval`
- Runs approval endpoint: `gateway/platforms/api_server_runs.py`
- API server toolset: `gateway/platforms/api_server.py`
- Windows installer: `scripts/install.ps1`

## Security finding

Upstream `tests/tools/test_request_tool_approval.py`는 `--yolo` 세션에서 Plugin의
approval gate가 우회되는 동작을 명시적으로 검증한다. 따라서 Hermes Runtime에는
main merge 실행 Tool을 등록하지 않는다. Hermes는 요청만 생성하고 실제 merge는
별도 사용자 승인 실행기가 수행한다.

## Change boundary

`hermes-v2026.9.7/`은 upstream 검증용 read-only checkout이다. 사내 기능은 이
저장소의 Plugin, Adapter, Skill, 설정으로만 구현한다.
