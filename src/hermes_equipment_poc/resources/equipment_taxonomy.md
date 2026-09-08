# Equipment Knowledge Taxonomy

이 파일은 모든 Agent가 공유하는 단일 기준이다. Agent Prompt에 분류 정의를 복제하지 않는다.

| Code | Name | Scope |
|---|---|---|
| 00 | External | 외부 의사결정, 메일, 외부 보고 및 협의 |
| 01 | Equipment Requirement / Specification | 설비 요구사항 및 사양 |
| 02 | Design Change / Risk | 설계 변경, 변경 검토, 리스크 |
| 03 | Meeting / Issue | 회의록, 이슈, Action Item |
| 04 | Equipment Decision | 설비 내부 의사결정, 설계 선택 근거, 기술 판단 |
| 05 | Test / Experiment / Result | 시험, 실험, 검증, 결과 |
| 06 | Operation / Trouble / Alarm | 운영, 장애, 알람, 트러블슈팅 |
| 07 | Deliverable / Report | 보고서, 산출물, 정리문서 |

## Scope selection

- 요구사항 확인: `01`, 필요 시 `00`, `04`
- 변경 영향 분석: `01`, `02`, `04`, `05`
- Trouble 분석: `01`, `02`, `04`, `05`, `06`
- 보고서 작성: 근거 계통 + `07`
- 검색 범위를 임의로 전체 확대하지 말고, 부족한 근거가 확인될 때 단계적으로 확장한다.

