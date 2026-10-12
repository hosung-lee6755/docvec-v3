"""워크플로우 API 패키지.

기능별로 나눈 라우터를 하나로 합쳐 `router` 로 노출한다(api/v1/router.py 가 `/workflows` 에 마운트).

- definitions: 정의 목록·생성·수정·복제·삭제, 블록 타입 목록
- versions:    버전 초안 생성·그래프 저장·게시·삭제
- runs:        실행 시작·목록·검토 재개/반려·내보내기·조회·삭제

등록 순서가 곧 매칭 순서다. 고정 경로(`/block-types`)가 `/{workflow_id}` 보다 먼저 와야 한다.
정의 라우터에는 빈 경로("") 라우트가 있어 prefix 없이는 include 할 수 없으므로,
정의 라우터를 기준으로 나머지를 붙인다.
"""
from . import definitions, runs, versions
from .definitions import list_block_types
from .runs import run_workflow
from .schemas import GraphUpdate
from .versions import publish_version, update_graph

router = definitions.router
router.include_router(versions.router)
router.include_router(runs.router)

__all__ = [
    "GraphUpdate",
    "list_block_types",
    "publish_version",
    "router",
    "run_workflow",
    "update_graph",
]
