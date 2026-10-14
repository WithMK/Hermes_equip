# 프로젝트 자료 등록 · 자동 인덱싱 (0.8.0)

프로젝트를 선택하고 `프로젝트 자료`에서 파일을 등록하면 EquipmentRAG가 원본 보관,
텍스트 추출, 분할, Embedding, 검색 인덱스 갱신을 수행합니다. 화면에서 대기·처리 중·
준비 완료·실패 상태를 확인하고 실패 작업을 재시도할 수 있습니다.
검색 자료를 만든 기능이며 모델 학습이나 업무용 산출물 자동 생성 기능은 아닙니다.

## 운영 설정

먼저 EquipmentRAG의 **managed-document-ingestion 변경(0.3.0-rc.3)** 을 배포합니다.
구버전 RAG는 새 쓰기 API를 제공하지 않습니다. A/O는 기존 project-memory 변경을
포함한 0.8.0 브랜치를 사용합니다. C/M과 llama.cpp 설정은 기존 구성을 사용합니다.

1. RAG 서버: `document.enabled: true`, 로컬 Embedding 모델과 문서 Collection을 설정합니다.
   SQLite FTS5를 쓰면 lexical backend/path 및 hybrid 검색 설정을 확인합니다.
2. 양쪽 서비스 프로세스에 동일한 `EQUIPMENT_RAG_INGESTION_KEY` 환경변수를 설정합니다.
   최소 24자이며 검색용 `EQUIPMENT_RAG_API_KEY`와 별개입니다.
3. RAG 실행 명령에 `--ingestion-root D:\EquipmentRAG-data\uploads`를 추가합니다.
4. 기존 `python -m hermes_equipment_poc.web_cli` 실행 명령에 `--enable-document-uploads`를 추가합니다.
   `--equipment-rag-base-url`로 기존 검색과 동일한 RAG 서버에 연결합니다.

키는 서버 사이에서만 전달됩니다. 브라우저 요청은 기존 A/O의 루프백·동일 출처 정책을
사용합니다. 파일은 HTTP로 전달하므로 A/O PC와 RAG PC의 공유 폴더가 필요 없습니다.
RAG 쓰기 연결이 없으면 기존 프로젝트·업무 실행은 계속 사용할 수 있습니다.

## 사용 순서

1. 프로젝트 생성 또는 선택. 장비 업무라면 기본 대상 ID를 먼저 설정합니다.
2. MD/TXT/PDF/DOCX/PPTX/XLSX 파일 하나를 등록합니다. 최대 10 MiB입니다.
3. `준비 완료`를 확인하고 같은 프로젝트에서 문서 관련 질문을 실행합니다.
4. 내용이 바뀌면 같은 이름의 파일을 다시 선택합니다. 교체 확인 후 버전을 검사합니다.
   같은 내용이면 중복 처리하지 않습니다. 다른 이름은 별도 자료로 등록됩니다.
5. 실패하면 RAG 설정·로그를 확인한 뒤 `재시도`를 누릅니다.

자료 등록 관리는 **A/O 자체 웹 화면**에서 합니다. OpenWebUI는 기존 프로젝트 모델
`ao/<domain>/<workspace>/project/<id>`를 선택해 이 자료를 질문에 사용할 수 있습니다.
OpenWebUI의 자체 파일 첨부를 이 등록 API로 전달하는 기능은 포함하지 않습니다.

첫 업로드 때 영속 namespace를 예약합니다. 문서 검색 Project 값이 비어 있으면
고유 값을 자동 설정합니다. 기존 값이 있으면 유지하므로 기존 RAG 자료와 함께 검색됩니다.
여러 프로젝트에 같은 검색 값을 수동 지정하면 검색 자료를 공유하는 구성입니다.
namespace는 등록 목록과 파일 소유권을 구분하며 사용자 권한 경계는 아닙니다.

등록 후 문서 검색 Project와 기본 대상 ID는 고정합니다. 이를 바꾸면 자료가 검색에서
누락될 수 있기 때문입니다. 변경이 필요하면 새 프로젝트를 만드세요. 통신 실패가
나더라도 예약은 유지하여 재요청이 같은 namespace를 사용합니다.
문서 domain의 일반 대상 ID는 equipment 필터로 보내지 않고 RAG 기본 equipment를
사용합니다. 설비 domain에서는 프로젝트의 기본 대상 ID를 전달합니다.
보관 프로젝트는 조회만 가능합니다.

## 저장과 상태

- A/O의 `.projects.db`: 프로젝트별 namespace, 검색 연결 값, 변경 이력.
- RAG의 `ingestion.db`: 최신 원본 파일, SHA-256, 버전, 처리 상태, 소유 Chunk ID.
- RAG의 기존 Chroma와 선택한 FTS5: 실제 검색 자료.

서버 중단 후 RAG의 처리 중 작업을 복구합니다. 파일 교체 시 과거 원본 이력은
보관하지 않습니다. 두 서비스 상태 및 검색 인덱스를 함께 백업하세요.
인덱스 부분 쓰기 실패 시 해당 범위 검색은 503으로 중단되며 재시도 완료 후 복구됩니다.
파싱 실패는 기존 검색 자료를 유지하므로 상태가 실패인 경우 이전 내용이 검색될 수 있습니다.
현재 범위는 등록 직후 자동 인덱싱입니다. 폴더 감시·삭제·외부 사이트 수집·Agent 배정은
후속 기능입니다. 스캔 문서 OCR은 RAG의 기존 오프라인 OCR 설정을 따릅니다.

## 검증 및 대상 PC 확인

```powershell
python -m unittest discover -s tests -v
python tests/material_integration_smoke.py --rag-root ..\EquipmentRAG
```

통합 smoke는 두 변경 브랜치의 checkout과 RAG 의존성이 필요합니다. 실제 HTTP,
Chroma, SQLite FTS5, A/O 작업 경로를 사용하지만 Embedding·Chat은 합성 fixture입니다.
로컬 모델 답변 품질과 실제 파일별 추출은 검증하지 않습니다.

대상 PC에서는 프로젝트 두 개에 서로 다른 문서를 등록하고, 준비 완료 후 근거 분리,
파일 교체 후 최신 내용 검색, 잘못된 문서 실패·재시도, RAG 재시작 후 상태 유지를 확인하세요.
이번 실행 환경에서는 브라우저 화면의 클릭 검증을 수행하지 못했으므로 화면 동작도
이 대상 PC 확인에 포함합니다.
