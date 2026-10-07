# Phase 6A — KnowledgeProvider boundary

This phase modularizes retrieval, not the entire equipment-oriented orchestrator.
No EquipmentRAG or ContextManager server change and no state schema migration is required.

## Responsibilities

- A/O selects when to search and controls tasks, delegation, evidence and artifacts.
- `KnowledgeProvider.search(KnowledgeQuery)` returns a `KnowledgeResult` containing
  provider identity and cited sources. It does not generate answers or modify an index.
- `EquipmentRagKnowledgeProvider` translates `subject_id` to EquipmentRAG's `equipment`
  filter and scopes to the existing 00–07 taxonomy through `EquipmentRagClient`.
- EquipmentRAG keeps its existing `/v1/retrieve` API and search/index implementation.
- A/O supplies retrieved evidence to C/M; C/M handles the active session/token budget
  and forwards inference to llama.cpp. C/M should not perform a second automatic RAG search.

Production CLI and web launchers explicitly construct the adapter. Legacy
`SingleOrchestrator(store, rag, chat)` and `rag=` integrations remain supported.
Pass exactly one of `rag` and `knowledge_provider`.

```python
from hermes_equipment_poc.knowledge import EquipmentRagKnowledgeProvider

engine = SingleOrchestrator(
    store,
    chat=chat,
    knowledge_provider=EquipmentRagKnowledgeProvider(rag_client),
)
```

Other providers implement `search(request)` and return `KnowledgeResult("provider-id", sources)`.
Sources have a unique non-empty `source_id` per result, `source_type` (`code` or `document`),
provider-local `record_id`, `text` or `code` content and optional label fields
(`file_name`, `relative_path`, `class_name`, `method_name`, `section`). Existing source
metadata is retained. Provider identity is saved in the retrieval checkpoint.
The adapter accepts older EquipmentRAG responses missing source IDs/types, but rejects
malformed arrays, invalid source types and duplicate IDs. Errors propagate; there is no
silent alternative search or ungrounded-answer fallback. Empty/contentless results
retain the existing no-evidence path. Existing evidence budget/citation validation applies.

## llama.cpp configuration

Default CLI/web `--context-model`: `Qwen3.8-27B-UD-Q5_K_XL.gguf`.
This is a request model ID, not a local model file loader or model download.
If llama.cpp is started with `--alias local-qwen`, use `--context-model local-qwen` instead.
Confirm the actual served ID in the target server's `/v1/models` response.
C/M's upstream should point at llama.cpp's OpenAI-compatible endpoint, commonly
`http://127.0.0.1:8080/v1`; A/O continues pointing at C/M, commonly port 8091.
Hermes specialist gateway model names (such as `document-agent`) are distinct from the
upstream GGUF model ID. Profile `model.default` controls their upstream model.
No Ollama service, Ollama API, or Ollama model tag is required for this route.

## Boundaries and next steps

- No dynamic provider loading from browser input; composition is operator-owned Python code.
- `subject_id` is a retrieval filter, NOT authorization. Neither workspace ID nor this
  adapter establishes RAG tenant isolation. Keep endpoints/indexes restricted per deployment.
- One provider per orchestrator in this phase; multi-provider fusion and globally namespaced
  evidence persistence are deferred.
- Public Task/UI/checkpoint requests retain `equipment_id` and current routing/prompts.
  Subject/metadata schema migration, Domain Packs and generic routing are later phases.
- Existing Hermes knowledge tools still use EquipmentRagClient; this change modularizes
  the A/O retrieval boundary, not every specialist's domain-specific tool.
- Ingestion, dataset production and index writes are not part of this read-only contract.

## Verification

Run `python -m unittest discover -s tests -v` after installing `.[web,test]`, or set
`PYTHONPATH=src`. Tests cover adapter wire payloads, subject/scope translation,
malformed/empty/error responses, independent provider substitution, legacy calls,
and default/aliased model IDs forwarded to C/M.

Target PC acceptance still required: real EquipmentRAG retrieval with equipment/scope,
C/M session continuity and llama.cpp inference, specialist delegation, citation-bearing
4A artifacts, and the Phase 5 browser checks. Local fakes do not verify live models.
