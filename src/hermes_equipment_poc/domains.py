"""Operator-selected built-in domain policies. No executable manifest loading."""
from dataclasses import dataclass
import re

class EquipmentClassifier:
    _CODE_CHANGE = (
        "코드 수정",
        "코드 변경",
        "코드를 수정",
        "코드를 변경",
        "구현해",
        "fix ",
        "implement",
        "refactor",
    )
    _TROUBLESHOOTING = (
        "알람",
        "장애",
        "고장",
        "원인",
        "트러블",
        "alarm",
        "error",
        "failure",
        "trouble",
    )
    _CODE_ANALYSIS = (
        "코드 분석",
        "소스 분석",
        "클래스",
        "메서드",
        "시퀀스",
        "code analysis",
        "class ",
        "method ",
        "sequence",
    )
    _DOCUMENT = (
        "문서",
        "사양서",
        "회의록",
        "매뉴얼",
        "보고서",
        "document",
        "manual",
        "specification",
        "report",
    )

    def classify(self, request) -> str:
        if request.request_kind is not None:
            return request.request_kind
        objective = request.objective.casefold()
        for kind, keywords in (
            ("code_change", self._CODE_CHANGE),
            ("troubleshooting", self._TROUBLESHOOTING),
            ("code_analysis", self._CODE_ANALYSIS),
            ("document_task", self._DOCUMENT),
        ):
            if any(keyword in objective for keyword in keywords):
                return kind
        return "question"


@dataclass(frozen=True)
class DomainPack:
    domain_id: str
    instruction: str
    allowed_kinds: tuple[str, ...]
    scopes: tuple[str, ...]
    subject_label: str
    no_evidence: str

    @property
    def allowed_agents(self) -> tuple[str, ...]:
        if self.domain_id == "document":
            return ("document-agent",)
        return ("document-agent", "code-analysis-agent", "troubleshooting-agent", "code-development-agent")

    def classify(self, request) -> str:
        if self.domain_id == "document":
            return request.request_kind or "document_task"
        return EquipmentClassifier().classify(request)

    def retrieval(self, request, kind: str) -> tuple[bool, str, str, tuple[str, ...]]:
        query = request.objective.strip()
        if request.subject_id:
            query = f"{request.subject_id} {query}"
        if self.domain_id == "document":
            return True, "document", query, ()
        if kind == "document_task":
            return True, "document", query, request.knowledge_scopes
        if kind == "code_analysis":
            return True, "code", query, ()
        if kind in {"troubleshooting", "code_change"} or request.equipment_id or request.knowledge_scopes or re.search(
            r"(?<![A-Za-z0-9])[A-Za-z]{1,12}[-_]\d{1,12}(?![A-Za-z0-9])", request.objective
        ):
            return True, "all", query, request.knowledge_scopes
        return False, "all", query, ()

    def validate(self, kind: str | None, scopes: tuple[str, ...]) -> None:
        if kind is not None and kind not in self.allowed_kinds:
            raise ValueError(f"request kind is not supported by {self.domain_id}")
        if set(scopes) - set(self.scopes):
            raise ValueError(f"invalid knowledge scopes for {self.domain_id}")


EQUIPMENT = DomainPack(
    "equipment", "You are the Agent Orchestra for equipment software work. ",
    ("question", "document_task", "code_analysis", "troubleshooting", "code_change"),
    tuple(f"{i:02d}" for i in range(8)), "Equipment",
    "검색된 설비 코드·문서 근거가 없어 근거 기반 결과를 생성할 수 없습니다. "
    "대상 설비, 알람 코드 또는 필요한 문서 범위를 확인해 주세요.",
)
DOCUMENT = DomainPack(
    "document", "You are the Agent Orchestra for general document analysis and report writing. ",
    ("question", "document_task"), (), "Subject",
    "검색된 문서 근거가 없어 결과를 생성할 수 없습니다. 문서 등록과 검색 범위를 확인해 주세요.",
)


def get_domain(domain_id: str) -> DomainPack:
    for pack in (EQUIPMENT, DOCUMENT):
        if pack.domain_id == domain_id:
            return pack
    raise ValueError(f"unknown domain: {domain_id}")
