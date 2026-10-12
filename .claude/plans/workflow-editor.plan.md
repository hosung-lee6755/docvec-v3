# Plan: 워크플로우 에디터 (Workflow Editor)

**Source PRD**: `.claude/prds/document-rag-platform-v2.prd.md`
**Selected Milestone**: #4 워크플로우 에디터 — 사용자가 고정 처리 블록을 조합해 문서 처리 흐름을 구성·실행
**Complexity**: Large

## Summary
Add a net-new subsystem that lets users compose fixed processing blocks (입력/전처리/분류/개체추출/키워드추출/요약/검증/조건분기/병합/후처리/출력) into a document-processing workflow, save it as a versioned definition, and run it against documents/collections. This is architecturally new — Project_1's existing pipeline is a *fixed* Celery chain (ingest → parse → chunk → embed); the workflow engine generalizes that into a *user-configurable DAG* (branch/merge blocks require this, not a linear chain). AI assists only by suggesting/validating block combinations from the fixed registry — never free-form code generation — and every edit to an active workflow version is diffed and requires explicit approval (per `docs/design/문서_처리_플랫폼_디자인_설계서.md` §4.5, §3.3). Adds one new top-level nav item ("워크플로우"), so this touches the existing IA (`Layout.tsx`, `App.tsx`).

## Patterns to Mirror
| Category | Source | Pattern |
|---|---|---|
| Naming | `backend/app/api/v1/endpoints/collections.py` | Router file per resource; Pydantic `XCreate`/`XUpdate`/`XResponse` schemas defined inline above the routes; `router = APIRouter()`, registered in `app/api/v1/router.py` with `prefix=`/`tags=` |
| Data access | `backend/app/db/models/processing_job.py` | SQLAlchemy `Mapped`/`mapped_column`, UUID PK via `default=uuid4`, `SQLEnum(...)` for status columns, `created_at`/`updated_at` with `onupdate=datetime.utcnow` |
| Status tracking | `backend/app/pipeline/job_tracker.py` | `start_job`/`complete_job`/`fail_job` helpers — reuse this exact shape for `WorkflowRun`/`WorkflowRunStep` status transitions (QUEUED→RUNNING→COMPLETED/FAILED) |
| Async task orchestration | `backend/app/pipeline/tasks/pipeline.py`, `celery_app.py` | Celery `chain()`/`.delay()` — but a fixed linear chain cannot express 조건분기/병합, so the workflow executor needs a custom step-by-step dispatcher (see Task 3) instead of a single static `chain()` |
| Adapter/plugin interface | `backend/app/pipeline/adapters/base.py` | `ABC` with `@abstractmethod` + a capabilities dataclass — mirror this shape for the block registry (`BaseBlock`, one class per block type) |
| Access control | `backend/app/api/v1/permissions.py` (`check_collection_access`, `check_project_access`) | Reuse project/collection-scoped permission checks for workflow CRUD — a workflow belongs to a project the same way a collection does |
| Errors | `collections.py` (e.g. line ~135, ~286) | `HTTPException(status_code=404/403/409, detail="<Korean message>")` |
| Frontend data hooks | `frontend/src/hooks/useCollections.ts` | One `use*.ts` file per resource; `useQuery`/`useMutation` from `@tanstack/react-query`; types exported from the same file; `queryClient.invalidateQueries` on mutation success |
| Frontend routing | `frontend/src/App.tsx` | Nested `<Route>` under the `Layout` protected route; project-scoped resources also nested under `projects/:projectId` |
| Frontend nav | `frontend/src/components/Layout.tsx` | `navItems` array entry `{ to, icon, label }`, optional `adminOnly` |
| Backend tests | `backend/tests/unit/test_collection_vector_stats.py` | `pytest.mark.asyncio`, `AsyncMock`/`MagicMock`, `patch(...)` on the module path where the endpoint imports the dependency, plain endpoint-function call (not full HTTP client) |

## Files to Change

| File | Action | Why |
|---|---|---|
| `backend/app/db/models/workflow.py` | CREATE | `WorkflowDefinition`, `WorkflowVersion` (versioned, immutable-once-published), `WorkflowBlockInstance`, `WorkflowEdge` |
| `backend/app/db/models/workflow_run.py` | CREATE | `WorkflowRun` (QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED), `WorkflowRunStep` (per-block execution record) |
| `backend/alembic/versions/xxxx_add_workflow_tables.py` | CREATE | Migration for the above (generate via `alembic revision --autogenerate`) |
| `backend/app/pipeline/blocks/base.py` | CREATE | `BaseBlock` ABC: `block_type`, `input_schema`, `output_schema`, `run(context) -> BlockResult` — mirrors `adapters/base.py` |
| `backend/app/pipeline/blocks/{input,preprocess,classify,extract_entities,extract_keywords,summarize,validate,branch,merge,postprocess,output}.py` | CREATE | One module per fixed block type from the design doc's 블록 유형 table |
| `backend/app/pipeline/blocks/registry.py` | CREATE | `BLOCK_REGISTRY: dict[str, type[BaseBlock]]` — single source of truth for valid block types (backend validation + `/workflows/block-types` API) |
| `backend/app/pipeline/tasks/workflow.py` | CREATE | `run_workflow_step(run_id, block_instance_id)` Celery task: execute one block, resolve outgoing edges (conditional edges evaluate a predicate against the block's output), enqueue next block(s); a 병합 block waits until all incoming edges for that run have completed before firing |
| `backend/app/services/workflow_service.py` | CREATE | Graph validation (cycle detection, required-input check, unreachable-block check) run before save and before execution — mirrors "저장 전 워크플로우 유효성 검사" requirement |
| `backend/app/api/v1/endpoints/workflows/` (패키지) | CREATE | CRUD for `WorkflowDefinition`/`WorkflowVersion`, `POST /workflows/{id}/versions` (new version, never mutate published), `POST /workflows/{id}/run`, `GET /workflows/{id}/runs`, `GET /workflows/block-types` |
| `backend/app/api/v1/router.py` | UPDATE | Register `workflows.router` (mirror existing `include_router` lines) |
| `frontend/src/hooks/useWorkflows.ts` | CREATE | `useWorkflows`, `useWorkflow`, `useCreateWorkflow`, `useSaveWorkflowVersion`, `useRunWorkflow`, `useWorkflowRuns` — mirror `useCollections.ts` |
| `frontend/src/pages/WorkflowsPage.tsx` | CREATE | List view — 목록 컬럼: 워크플로우명/설명/버전/상태/문서유형/수정자/수정일 (design doc §4.4) |
| `frontend/src/pages/WorkflowEditorPage.tsx` | CREATE | 3-pane layout: block palette / canvas / block property panel (design doc §4.5 ASCII layout) |
| `frontend/src/components/workflow/BlockPalette.tsx`, `WorkflowCanvas.tsx`, `BlockPropertyPanel.tsx` | CREATE | Canvas subcomponents |
| `frontend/package.json` | UPDATE | Add a node-graph/canvas library (recommend `@xyflow/react` — de facto standard for this exact block+edge canvas UI) — **flag to user before installing, this is a new runtime dependency** |
| `frontend/src/App.tsx` | UPDATE | Add `<Route path="workflows" .../>` and `<Route path="workflows/:id/edit" .../>`, both top-level and under `projects/:projectId` (consistent with how `collections`/`search`/`chat` are dual-registered) |
| `frontend/src/components/Layout.tsx` | UPDATE | Add `{ to: '/workflows', icon: Workflow, label: '워크플로우' }` to `navItems` |
| `backend/tests/unit/test_workflow_endpoints.py`, `test_workflow_service.py` | CREATE | CRUD + validation + version-immutability tests |
| `backend/tests/unit/test_workflow_execution.py` | CREATE | Executor tests: linear chain, branch-true/false path, merge waits for all incoming edges |

## Tasks

### Task 1: Data model + migration
- **Action**: Define `WorkflowDefinition` (id, project_id, name, description, status: DRAFT/ACTIVE/INACTIVE), `WorkflowVersion` (id, workflow_id, version_number, block_graph snapshot, published_at, created_by — immutable once `published_at` is set), `WorkflowBlockInstance` (id, version_id, block_type, position, config json), `WorkflowEdge` (id, version_id, from_block_id, to_block_id, condition json nullable — null = unconditional), `WorkflowRun` (id, version_id, document_id nullable/collection_id nullable, status, started_at, completed_at), `WorkflowRunStep` (id, run_id, block_instance_id, status, input json, output json, error_message).
- **Mirror**: `app/db/models/processing_job.py` column conventions.
- **Validate**: `cd backend && alembic upgrade head && alembic check`

### Task 2: Block registry (fixed, pluggable)
- **Action**: `BaseBlock` ABC + one concrete class per block type in the design doc's table. Each declares its `input_schema`/`output_schema` (Pydantic) and a `run(context: BlockContext) -> BlockResult`. Register all in `BLOCK_REGISTRY`.
- **Mirror**: `app/pipeline/adapters/base.py`.
- **Validate**: `pytest backend/tests/unit/test_block_registry.py`

### Task 3: Execution engine (DAG walker, not a static chain)
- **Action**: `run_workflow_step` Celery task. On block completion: evaluate each outgoing `WorkflowEdge` (conditional edges test `condition` against the block's output); for each edge whose target is NOT a 병합 block, enqueue immediately; for a 병합 target, increment a completed-incoming-edge counter on that `WorkflowRunStep` and only enqueue once the counter reaches the block's total incoming-edge count. Reuse `job_tracker.py`'s start/complete/fail shape at the `WorkflowRunStep` level.
- **Mirror**: `app/pipeline/tasks/pipeline.py` for Celery task composition style; `app/pipeline/job_tracker.py` for status transitions.
- **Validate**: `pytest backend/tests/unit/test_workflow_execution.py` (linear / branch / merge cases)

### Task 4: Validation service
- **Action**: `workflow_service.validate_graph(version)` — cycle detection, every non-입력 block has ≥1 incoming edge, every non-출력 block has ≥1 outgoing edge, required `config` fields present per block type. Called on save (draft) and required to pass before `publish`/`run`.
- **Mirror**: existing `HTTPException(409, ...)` pattern for a failed validation on publish.
- **Validate**: `pytest backend/tests/unit/test_workflow_service.py`

### Task 5: API endpoints
- **Action**: `workflows.py` router — list/create/get workflows; `POST /workflows/{id}/versions` creates a new draft version (never edits a published one — enforce in code, return 409 on attempted mutation of a published version); `POST /workflows/{id}/publish`; `POST /workflows/{id}/run`; `GET /workflows/{id}/runs`, `GET /workflows/runs/{run_id}`; `GET /workflows/block-types` (drives the frontend palette from `BLOCK_REGISTRY`, avoiding a hardcoded duplicate list in the frontend).
- **Mirror**: `collections.py` end-to-end (schemas inline, permission check via `check_project_access`, `HTTPException` detail messages in Korean).
- **Validate**: `pytest backend/tests/unit/test_workflow_endpoints.py`

### Task 6: Frontend data hooks
- **Action**: `useWorkflows.ts` — `useWorkflows(projectId)`, `useWorkflow(id)`, `useCreateWorkflow`, `useSaveDraftVersion`, `usePublishVersion`, `useRunWorkflow`, `useWorkflowRuns(id)`, `useBlockTypes()`.
- **Mirror**: `useCollections.ts` exactly (query keys, invalidation on mutation success).
- **Validate**: `cd frontend && npx vitest run src/hooks` (once hook tests exist) + `tsc --noEmit`

### Task 7: Workflow list page
- **Action**: `WorkflowsPage.tsx` — table per design doc §4.4 columns (워크플로우명/설명/버전/상태/문서유형/수정자/수정일), row actions: 생성/복제/수정/비활성화/버전 비교/실행 이력.
- **Mirror**: existing list pages (`CollectionsPage.tsx`) for table/empty-state conventions.

### Task 8: Workflow editor canvas page
- **Action**: `WorkflowEditorPage.tsx` — 3-pane layout (palette / canvas / property panel). Use `@xyflow/react` for the canvas (nodes = block instances, edges = `WorkflowEdge`, edge validity enforced client-side before the save-time server validation). Block property panel edits `config` json for the selected node. Saving from a published version always creates a new draft version (never PATCHes a published one) — surfaced in the UI as "새 버전으로 저장", matching the design doc's "활성 버전은 직접 수정하지 않고 새 버전으로 저장한다" rule.
- **Mirror**: `Layout.tsx`'s 3-column inline-style approach for consistency with the rest of the app (no new CSS framework).
- **Validate**: manual browser check (start dev server, create workflow, add blocks, connect, save, run) — per this session's UI-testing requirement.

### Task 9: IA integration
- **Action**: Add `워크플로우` to `Layout.tsx` `navItems`; register routes in `App.tsx` both top-level and nested under `projects/:projectId` (matches how `collections`/`search`/`chat` are already dual-registered).
- **Mirror**: existing dual top-level + project-nested route registration in `App.tsx`.

### Task 10: Tests
- **Action**: Backend — endpoint tests (CRUD, version-immutability-on-publish, 409 on mutating a published version), execution tests (linear, branch-true, branch-false, merge-waits-for-all-inputs), validation tests (cycle rejected, missing required config rejected). Frontend — hook tests for `useWorkflows`.
- **Mirror**: `test_collection_vector_stats.py` (`AsyncMock`, `patch` at import site, direct endpoint function calls).
- **Validate**: `cd backend && pytest --cov=app --cov-report=term-missing` (target ≥80% on new modules)

## Validation
```bash
cd backend && alembic upgrade head
cd backend && pytest backend/tests/unit/test_workflow_*.py -v
cd backend && pytest --cov=app.pipeline.blocks --cov=app.services.workflow_service --cov-report=term-missing
cd frontend && tsc --noEmit
cd frontend && npx vitest run
```

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| DAG executor (branch/merge) is materially more complex than Project_1's existing linear Celery `chain()` — easy to underestimate | High | Build and test the executor (Task 3) in isolation with unit tests before wiring any real block logic; keep block `run()` implementations trivial/stubbed until the executor itself is proven |
| New frontend dependency (`@xyflow/react` or equivalent) changes `package.json`/lockfile | Medium | Confirm with user before running `pnpm add`; this is flagged separately from the rest of the plan |
| IA change (new top-level nav item + nested routes) risks breaking existing `ProjectWorkspace` nested-route assumptions | Medium | Add routes additively first, verify existing nested routes (`collections`, `search`, `chat`) still resolve correctly after the change |
| AI-assisted block suggestion scope creep (design doc explicitly limits AI to combining registered blocks, not free-form generation) | Low | Enforce in the API layer: any AI suggestion endpoint returns only `block_type` values present in `BLOCK_REGISTRY` |
| Version-immutability rule (no direct edit of published workflow) not enforced consistently across both API and UI | Medium | Enforce at the API layer (409 on PATCH to a published version) as the source of truth; UI is a courtesy, not the only enforcement point |

## Acceptance
- [ ] All tasks complete
- [ ] Validation passes (`pytest`, `tsc --noEmit`, `vitest`)
- [ ] Patterns mirrored: schema-per-endpoint-file, `job_tracker`-style status helpers, adapter-style block registry, `useCollections`-style hooks, dual top-level/project-nested routes
- [ ] A published workflow version cannot be mutated directly (only via new-version-then-publish)
- [ ] A workflow containing a 조건분기 + 병합 pair executes correctly (both branches conditionally taken, merge waits for both)
- [ ] `docs/design/문서_처리_플랫폼_디자인_설계서.md` §4.4/§4.5 requirements (list columns, block types, editing rules) are all represented
