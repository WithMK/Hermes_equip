# Hermes Equipment PoC 폐쇄망 설치

이 절차는 인터넷 연결 Windows PC에서 번들을 한 번 생성하고, 생성된 ZIP을 폐쇄망
Windows 11 PC로 반입해 설치하는 방식이다. 폐쇄망 설치 중에는 인터넷이나 사내
EquipmentRAG/ContextManager가 없어도 된다.

## 포함 범위

| 항목 | 고정 값 / 처리 |
|---|---|
| Hermes | `v2026.9.7`, commit `2237be355906fbe6065ce1815711eee52b2d646e`, package `0.21.1` |
| Python | Windows x64 `3.11.9`, 설치 디렉터리 내부에만 설치 |
| Git | PortableGit `2.54.0`, 설치 디렉터리 내부에만 압축 해제 |
| Hermes extras | `mcp`만 포함 |
| Equipment PoC | `hermes-equipment-poc==0.2.0`, Plugin, Skills, 4개 Agent profile |
| 검증 | 전체 파일 SHA-256, 오프라인 재설치, `pip check`, Python import, Git 실행 |

브라우저 자동화, unrestricted terminal, cron, Home Assistant, 실제 설비제어 및 production
배포 기능은 포함하지 않는다. 이는 Hermes 전체 기능 번들이 아니라 현재 PoC에 필요한
최소 실행 번들이다.

## 1. 인터넷 연결 PC에서 번들 생성

### 준비 조건

- Windows 11 x64
- Windows PowerShell 5.1 이상
- Git for Windows
- 인터넷에서 GitHub와 PyPI, python.org에 접근 가능
- 이 저장소를 clone 또는 ZIP으로 준비

PowerShell에서 저장소 루트로 이동한 뒤 실행한다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\Prepare-HermesOfflineBundle.ps1
```

기본 출력은 저장소의 상위 디렉터리다.

```text
HermesEquipmentOfflineBundle\
HermesEquipmentOfflineBundle.zip
HermesEquipmentOfflineBundle.zip.sha256
```

스크립트는 다음을 자동 수행한다.

1. Python과 PortableGit 설치 파일을 다운로드한다.
2. 다운로드한 실행 파일의 Windows Authenticode 서명을 확인한다.
3. Hermes tag와 commit을 모두 확인한다.
4. Windows CPython 3.11용 Hermes Core, MCP 및 모든 전이 의존성을 wheel로 받는다.
5. Equipment PoC wheel을 만든다.
6. 새 venv에서 네트워크를 사용하지 않고 전체 wheelhouse를 재설치해 검증한다.
7. Plugin, Skills, profiles, 문서와 연결 점검 스크립트를 복사한다.
8. 모든 파일의 SHA-256 manifest와 반입용 ZIP을 만든다.

기존 출력이 있으면 기본적으로 중단한다. 검증 후 교체할 때만 명시적으로 `-Force`를
사용한다.

```powershell
.\scripts\Prepare-HermesOfflineBundle.ps1 -Force
```

## 2. 반입 전 무결성 확인

ZIP과 `.sha256` 파일을 함께 반입하고, 가능하면 출력된 SHA-256 값은 별도 승인 채널에도
기록한다.

```powershell
$expected = (Get-Content .\HermesEquipmentOfflineBundle.zip.sha256).Split(' ')[0]
$actual = (Get-FileHash .\HermesEquipmentOfflineBundle.zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "Offline bundle ZIP hash mismatch" }
```

`.sha256` 파일은 전송 오류 확인용이다. 악의적인 변조까지 방어하려면 조직의 코드서명
인증서로 ZIP 또는 manifest에 별도 서명하는 절차가 필요하다.

## 3. 폐쇄망 PC에서 설치

ZIP을 로컬 디스크에 완전히 압축 해제한 뒤, 관리자 권한이 아닌 일반 PowerShell에서
실행한다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
cd .\HermesEquipmentOfflineBundle
.\Install-HermesOffline.ps1
```

기본 설치 위치는 `%LOCALAPPDATA%\HermesEquipment`다. 시스템 Python, 시스템 Git,
시스템 PATH는 변경하지 않는다. PATH 등록이 필요할 때만 아래 옵션을 사용한다.

```powershell
.\Install-HermesOffline.ps1 -AddToUserPath
```

기존 설치 위치가 있으면 설치를 중단한다. `-Force`를 지정해도 삭제하지 않고
`HermesEquipment.backup-<UTC timestamp>`로 이동한 뒤 새로 설치한다.

설치 중 다음이 강제된다.

- manifest에 없는 파일 또는 SHA-256이 다른 파일이 하나라도 있으면 중단
- `pip --no-index --find-links <bundle>\wheelhouse` 사용
- Hermes `0.21.1`과 PoC `0.2.0` exact version 사용
- 설치 후 `pip check`와 import/Git smoke test 수행

## 4. 서비스 주소 설정

설치 후 `%LOCALAPPDATA%\HermesEquipment\profiles` 아래 네 profile의 `config.yaml`에서
모든 `REPLACE_...` 값을 변경한다.

- `model.default`: C/M이 노출하는 Local LLM model 이름
- `model.base_url`: ContextManager OpenAI-compatible `/v1` endpoint
- `equipment_rag.base_url`: 다른 PC의 EquipmentRAG 주소
- `workspace_root`: 허용할 설비제어SW 저장소의 절대 경로
- `git.approval_store`: workspace 외부의 승인 저장 경로
- `build.allowed_targets`: build/test를 허용할 solution 상대 경로
- `audit.path`: 감사 JSONL 저장 경로

필요한 profile에 `.env.example`을 `.env`로 복사하고 API key를 설정한다. 실제 credential은
번들, Git 저장소 또는 `config.yaml`에 기록하지 않는다.

```powershell
Copy-Item "$env:LOCALAPPDATA\HermesEquipment\profiles\document-agent\.env.example" `
  "$env:LOCALAPPDATA\HermesEquipment\profiles\document-agent\.env"
```

RAG/ContextManager가 나중에 다른 PC에서 준비되면 설치를 다시 하지 않고 URL만 변경한다.
연결 확인은 다음 스크립트를 사용한다.

```powershell
& "$env:LOCALAPPDATA\HermesEquipment\scripts\Test-ExternalServices.ps1" `
  -EquipmentRagBaseUrl http://RAG_PC_IP:8765 `
  -ContextManagerBaseUrl http://CONTEXT_PC_IP:8091
```

## 5. 실행

PATH를 변경하지 않은 기본 설치에서는 생성된 launcher를 사용한다.

```powershell
& "$env:LOCALAPPDATA\HermesEquipment\bin\hermes-equipment.cmd" -p document-agent
& "$env:LOCALAPPDATA\HermesEquipment\bin\hermes-equipment.cmd" -p code-analysis-agent
& "$env:LOCALAPPDATA\HermesEquipment\bin\hermes-equipment.cmd" -p troubleshooting-agent
& "$env:LOCALAPPDATA\HermesEquipment\bin\hermes-equipment.cmd" -p code-development-agent
```

각 profile은 서로 다른 API Server port를 사용한다. RAG가 없으면 검색 Tool만 실패한다.
ContextManager가 없으면 model 호출을 수행할 수 없으므로 Profile 설정과 Plugin Tool 목록까지만
독립적으로 검증한다.

## 6. 재현성과 업데이트

`manifest.json`과 설치 후 `installation.json`을 시험 증적으로 보관한다. Hermes 버전을
변경할 때는 준비 스크립트의 tag, commit, package version을 함께 변경하고 새 번들로
오프라인 설치 검증을 다시 통과해야 한다. 폐쇄망 PC에서 `pip install -U`나 Hermes 자동
업데이트는 실행하지 않는다.
