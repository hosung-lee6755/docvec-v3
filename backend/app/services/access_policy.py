"""v3 접근 정책 — 문서 열람 판정의 단일 출처.

규칙(.claude/plans/m1-permission-model.plan.md "권한 규칙"):
  - 업로더 본인은 자기 문서를 항상 본다.
  - 그 외에는 세 조건을 모두 만족해야 한다.
      1) 컬렉션 접근: 기존 규칙(소유자·프로젝트 상속·컬렉션 멤버) — 접근 가능 컬렉션 집합으로 표현
      2) 보안등급: 유효 등급 순위 <= 사용자 열람등급 순위
         유효 등급 = 문서 security_level → 컬렉션 default_security_level → Public
      3) ACL: 문서 ACL이 비어 있으면 제한 없음, 있으면 내 주체(u:<id>, g:<id>) 중 하나 포함

판정의 정본은 Postgres다. Qdrant 페이로드(sec_rank/acl/owner_id)는 검색 단계에서 거르기
위한 사본이며, 검색 결과는 LLM에 넣기 전에 Postgres 기준으로 다시 확인한다(fail-closed).

API(async 세션)와 채팅 워커(sync 세션)가 같은 규칙을 쓰도록, 컬렉션·그룹 조회는
SQLAlchemy 문(statement)으로만 만들고 실행만 각 세션 종류에 맡긴다.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, Range
from sqlalchemy import and_, case, exists, false, func, or_, select, tuple_, union
from sqlalchemy.sql import ColumnElement, Select

from app.db.models.collection import Collection
from app.db.models.collection_member import CollectionMember
from app.db.models.document import Document
from app.db.models.document_acl import DocumentAclEntry
from app.db.models.project import Project
from app.db.models.project_member import ProjectMember
from app.db.models.user_group import UserGroupMember

SECURITY_LEVELS: tuple[str, ...] = ("Public", "Internal", "Confidential")
_LEVEL_RANK: dict[str, int] = {level: i for i, level in enumerate(SECURITY_LEVELS)}
_LOWEST_RANK = 0
_HIGHEST_RANK = len(SECURITY_LEVELS) - 1

DEFAULT_CLEARANCE_LEVEL = "Internal"
DEFAULT_DOCUMENT_LEVEL = "Public"
UNRESTRICTED_ACL = "*"

PRINCIPAL_USER = "user"
PRINCIPAL_GROUP = "group"


# ---------------------------------------------------------------------------
# 순수 규칙
# ---------------------------------------------------------------------------

def clearance_rank(level: str | None) -> int:
    """사용자 열람등급 순위. 미지정은 기본값, 알 수 없는 값은 가장 낮게(fail-closed)."""
    if level is None:
        level = DEFAULT_CLEARANCE_LEVEL
    return _LEVEL_RANK.get(level, _LOWEST_RANK)


def document_level_rank(level: str | None) -> int:
    """문서 등급 순위. 알 수 없는 값은 가장 높게(fail-closed)."""
    if level is None:
        level = DEFAULT_DOCUMENT_LEVEL
    return _LEVEL_RANK.get(level, _HIGHEST_RANK)


def user_principal(user_id: str) -> str:
    return f"u:{user_id}"


def group_principal(group_id: str) -> str:
    return f"g:{group_id}"


def principal_key(principal_type: str, principal_id: str) -> str:
    if principal_type == PRINCIPAL_USER:
        return user_principal(principal_id)
    if principal_type == PRINCIPAL_GROUP:
        return group_principal(principal_id)
    raise ValueError(f"unknown principal_type: {principal_type}")


@dataclass(frozen=True)
class AccessContext:
    """한 사용자의 데이터 접근 범위 스냅샷(불변)."""

    user_id: str
    collection_ids: frozenset[str]
    clearance_rank: int
    group_ids: frozenset[str]

    @classmethod
    def create(
        cls,
        user_id: str,
        collection_ids: Iterable[str],
        clearance_level: str | None,
        group_ids: Iterable[str] = (),
    ) -> AccessContext:
        return cls(
            user_id=str(user_id),
            collection_ids=frozenset(str(c) for c in collection_ids),
            clearance_rank=clearance_rank(clearance_level),
            group_ids=frozenset(str(g) for g in group_ids),
        )

    @property
    def principals(self) -> frozenset[str]:
        groups = (group_principal(g) for g in self.group_ids)
        return frozenset({user_principal(self.user_id), *groups})

    @property
    def acl_match_values(self) -> frozenset[str]:
        """Qdrant `acl` 페이로드와 대조할 값 — 제한 없음 표식 + 내 주체."""
        return frozenset({UNRESTRICTED_ACL, *self.principals})

    def fingerprint(self) -> str:
        """같은 권한 조합이면 같은 값. 답변 캐시 키 등 권한별로 나눠야 하는 곳에 쓴다."""
        parts = [
            f"u={self.user_id}",
            f"r={self.clearance_rank}",
            "c=" + ",".join(sorted(self.collection_ids)),
            "g=" + ",".join(sorted(self.group_ids)),
        ]
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class DocumentAccessFacts:
    """문서 한 건의 열람 판정에 필요한 사실(불변)."""

    document_id: str
    created_by: str | None
    collection_id: str | None
    security_level: str | None
    collection_default_level: str | None
    acl_principals: frozenset[str]


def effective_level_rank(facts: DocumentAccessFacts) -> int:
    level = facts.security_level or facts.collection_default_level or DEFAULT_DOCUMENT_LEVEL
    return document_level_rank(level)


def can_view(ctx: AccessContext, facts: DocumentAccessFacts) -> bool:
    if facts.created_by is not None and str(facts.created_by) == ctx.user_id:
        return True
    if facts.collection_id is None or str(facts.collection_id) not in ctx.collection_ids:
        return False
    if effective_level_rank(facts) > ctx.clearance_rank:
        return False
    if facts.acl_principals and not (facts.acl_principals & ctx.principals):
        return False
    return True


RELAX_FORBIDDEN_DETAIL = "보안등급을 낮추거나 접근 제한을 푸는 일은 문서 업로더나 컬렉션 소유자만 할 수 있습니다"


def is_relaxing_level(old_level: str | None, new_level: str | None) -> bool:
    """유효 등급이 낮아지는지(더 많은 사람이 보게 되는지). None은 기본값(Public)으로 본다."""
    return document_level_rank(new_level) < document_level_rank(old_level)


def is_relaxing_acl(old_principals: Iterable[str], new_principals: Iterable[str]) -> bool:
    """허용 목록 교체가 접근을 넓히는지. 제한 해제(빈 목록)나 허용 대상 추가가 해당한다.
    처음 제한을 거는 것과 대상을 줄이는 것은 좁히는 방향이다."""
    old, new = set(old_principals), set(new_principals)
    return bool(old) and (not new or bool(new - old))


def can_relax(user_id: str, uploader_id: str | None, collection_owner_id: str | None) -> bool:
    """접근을 넓히는 변경은 문서 업로더와 컬렉션 소유자만 할 수 있다(관리자 예외 없음)."""
    return str(user_id) in {str(uploader_id), str(collection_owner_id)} - {"None"}


def document_access_payload(facts: DocumentAccessFacts) -> dict:
    """Qdrant 포인트에 넣는 권한 사본. 업로더는 ACL이 있을 때 항상 목록에 포함한다."""
    owner = str(facts.created_by) if facts.created_by is not None else None
    if facts.acl_principals:
        acl = set(facts.acl_principals)
        if owner:
            acl.add(user_principal(owner))
        acl_values = sorted(acl)
    else:
        acl_values = [UNRESTRICTED_ACL]
    return {"sec_rank": effective_level_rank(facts), "acl": acl_values, "owner_id": owner}


# ---------------------------------------------------------------------------
# Qdrant 필터
# ---------------------------------------------------------------------------

def qdrant_access_filter(
    ctx: AccessContext,
    collection_ids: Iterable[str] | None = None,
    extra: dict | None = None,
) -> Filter:
    """검색 단계 권한 필터.

    collection_ids: 이번 질의의 범위(단일 컬렉션·프로젝트 등). None이면 사용자의 접근 가능
    컬렉션 전체. 범위 밖 컬렉션은 소유 문서라도 나오지 않는다(v2 검색 동작과 동일).
    권한 페이로드가 없는 포인트(백필 전)는 어떤 조건에도 맞지 않아 걸러진다(fail-closed).
    """
    scope = list(collection_ids) if collection_ids is not None else sorted(ctx.collection_ids)
    must: list = [FieldCondition(key="collection_id", match=MatchAny(any=[str(c) for c in scope]))]
    for key, value in (extra or {}).items():
        must.append(FieldCondition(key=key, match=MatchValue(value=value)))
    permitted = Filter(
        must=[
            FieldCondition(key="sec_rank", range=Range(lte=ctx.clearance_rank)),
            FieldCondition(key="acl", match=MatchAny(any=sorted(ctx.acl_match_values))),
        ]
    )
    own = Filter(must=[FieldCondition(key="owner_id", match=MatchValue(value=ctx.user_id))])
    return Filter(
        must=[*must, Filter(should=[own, permitted])],
        must_not=[FieldCondition(key="disabled", match=MatchValue(value=True))],
    )


def qdrant_visibility_filter(ctx: AccessContext) -> Filter:
    """범위 지정 없는 가시성 필터 — document_visibility_clause의 Qdrant 판.

    업로더 본인 문서 OR (접근 가능 컬렉션 AND 등급 AND ACL). 문서 목록과 같은 결과 집합이
    필요한 경로(요약 검색)에서 쓴다. 접근 가능 컬렉션이 없어도 본인 문서는 나온다.
    """
    own = Filter(must=[FieldCondition(key="owner_id", match=MatchValue(value=ctx.user_id))])
    should: list = [own]
    if ctx.collection_ids:
        should.append(
            Filter(
                must=[
                    FieldCondition(
                        key="collection_id", match=MatchAny(any=sorted(ctx.collection_ids))
                    ),
                    FieldCondition(key="sec_rank", range=Range(lte=ctx.clearance_rank)),
                    FieldCondition(key="acl", match=MatchAny(any=sorted(ctx.acl_match_values))),
                ]
            )
        )
    return Filter(
        must=[Filter(should=should)],
        must_not=[FieldCondition(key="disabled", match=MatchValue(value=True))],
    )


# ---------------------------------------------------------------------------
# SQL — 컨텍스트 구성용 문(statement). async/sync 세션 모두 그대로 실행한다.
# ---------------------------------------------------------------------------

def accessible_collection_ids_stmt(user_id: str, project_id: str | None = None) -> Select:
    """기존 permissions.accessible_collection_ids 규칙을 그대로 옮긴 단일 UNION 문.

    소유 컬렉션 ∪ 멤버 컬렉션 ∪ (내가 속한 프로젝트의 restrict_to_members=False 컬렉션).
    project_id가 있으면 그 프로젝트의 컬렉션으로 좁히고, 그 프로젝트에 속하지 않았다면
    프로젝트 상속분은 비운다(방어적 교차 검증 — 상속분은 내 프로젝트 목록과 교차하므로 자동).
    """
    uid = str(user_id)
    user_projects = union(
        select(Project.id).where(Project.created_by == uid),
        select(ProjectMember.project_id).where(ProjectMember.user_id == uid),
    ).subquery()

    owned = select(Collection.id).where(Collection.created_by == uid)
    member = select(CollectionMember.collection_id).join(
        Collection, Collection.id == CollectionMember.collection_id
    ).where(CollectionMember.user_id == uid)
    via_project = select(Collection.id).where(
        Collection.project_id.in_(select(user_projects.c[0])),
        Collection.restrict_to_members.is_(False),
    )
    if project_id is not None:
        pid = str(project_id)
        owned = owned.where(Collection.project_id == pid)
        member = member.where(Collection.project_id == pid)
        via_project = via_project.where(Collection.project_id == pid)
    return select(union(owned, member, via_project).subquery().c[0])


def group_ids_stmt(user_id: str) -> Select:
    return select(UserGroupMember.group_id).where(UserGroupMember.user_id == str(user_id))


def document_facts_stmt(document_ids: Iterable[str]) -> Select:
    return (
        select(
            Document.id,
            Document.created_by,
            Document.collection_id,
            Document.security_level,
            Collection.default_security_level,
        )
        .outerjoin(Collection, Collection.id == Document.collection_id)
        .where(Document.id.in_([str(d) for d in document_ids]))
    )


def document_acl_stmt(document_ids: Iterable[str]) -> Select:
    return select(
        DocumentAclEntry.document_id, DocumentAclEntry.principal_type, DocumentAclEntry.principal_id
    ).where(DocumentAclEntry.document_id.in_([str(d) for d in document_ids]))


def build_document_facts(fact_rows: Iterable, acl_rows: Iterable) -> dict[str, DocumentAccessFacts]:
    acl: dict[str, set[str]] = {}
    for doc_id, ptype, pid in acl_rows:
        acl.setdefault(str(doc_id), set()).add(principal_key(ptype, str(pid)))
    facts: dict[str, DocumentAccessFacts] = {}
    for doc_id, created_by, collection_id, level, col_default in fact_rows:
        key = str(doc_id)
        facts[key] = DocumentAccessFacts(
            document_id=key,
            created_by=str(created_by) if created_by is not None else None,
            collection_id=str(collection_id) if collection_id is not None else None,
            security_level=level,
            collection_default_level=col_default,
            acl_principals=frozenset(acl.get(key, set())),
        )
    return facts


def _effective_rank_sql() -> ColumnElement:
    collection_default = (
        select(Collection.default_security_level)
        .where(Collection.id == Document.collection_id)
        .scalar_subquery()
    )
    level = func.coalesce(Document.security_level, collection_default, DEFAULT_DOCUMENT_LEVEL)
    return case(
        *[(level == name, rank) for name, rank in _LEVEL_RANK.items()],
        else_=_HIGHEST_RANK,
    )


def document_visibility_clause(ctx: AccessContext) -> ColumnElement:
    """Document 목록·집계 쿼리용 WHERE 조건 — can_view와 같은 규칙의 SQL 판."""
    acl_for_doc = DocumentAclEntry.document_id == Document.id
    principal_pairs = [
        (PRINCIPAL_USER, ctx.user_id), *((PRINCIPAL_GROUP, g) for g in ctx.group_ids)
    ]
    acl_principal = tuple_(DocumentAclEntry.principal_type, DocumentAclEntry.principal_id)
    acl_ok = or_(
        ~exists().where(acl_for_doc),
        exists().where(
            acl_for_doc,
            acl_principal.in_(principal_pairs),
        ),
    )
    shared = (
        and_(
            Document.collection_id.in_(sorted(ctx.collection_ids)),
            _effective_rank_sql() <= ctx.clearance_rank,
            acl_ok,
        )
        if ctx.collection_ids
        else false()
    )
    return or_(Document.created_by == ctx.user_id, shared)


# ---------------------------------------------------------------------------
# 세션별 실행기 — 규칙은 위 문/순수 함수만 쓴다.
# ---------------------------------------------------------------------------

async def build_access_context(db, user) -> AccessContext:
    """API(AsyncSession)용."""
    collection_ids = (await db.scalars(accessible_collection_ids_stmt(str(user.id)))).all()
    group_ids = (await db.scalars(group_ids_stmt(str(user.id)))).all()
    return AccessContext.create(user.id, collection_ids, user.clearance_level, group_ids)


def build_access_context_sync(db, user_id: str) -> AccessContext:
    """채팅 워커(sync Session)용 — 사용자 행을 직접 읽는다."""
    from app.db.models.user import User

    clearance = db.scalar(select(User.clearance_level).where(User.id == str(user_id)))
    if clearance is None:
        # 사용자 행이 없으면(삭제 등) 기본값(Internal)이 아니라 최저 등급으로 본다(fail-closed).
        clearance = SECURITY_LEVELS[_LOWEST_RANK]
    collection_ids = db.scalars(accessible_collection_ids_stmt(str(user_id))).all()
    group_ids = db.scalars(group_ids_stmt(str(user_id))).all()
    return AccessContext.create(user_id, collection_ids, clearance, group_ids)


async def load_document_facts(db, document_ids: Iterable[str]) -> dict[str, DocumentAccessFacts]:
    ids = [str(d) for d in document_ids if d]
    if not ids:
        return {}
    fact_rows = (await db.execute(document_facts_stmt(ids))).all()
    acl_rows = (await db.execute(document_acl_stmt(ids))).all()
    return build_document_facts(fact_rows, acl_rows)


def load_document_facts_sync(db, document_ids: Iterable[str]) -> dict[str, DocumentAccessFacts]:
    ids = [str(d) for d in document_ids if d]
    if not ids:
        return {}
    fact_rows = db.execute(document_facts_stmt(ids)).all()
    acl_rows = db.execute(document_acl_stmt(ids)).all()
    return build_document_facts(fact_rows, acl_rows)


def visible_document_ids(ctx: AccessContext, facts: dict[str, DocumentAccessFacts]) -> set[str]:
    return {doc_id for doc_id, f in facts.items() if can_view(ctx, f)}


async def collection_owner_id(db, collection_id) -> str | None:
    if collection_id is None:
        return None
    owner = await db.scalar(select(Collection.created_by).where(Collection.id == str(collection_id)))
    return str(owner) if owner is not None else None


async def can_relax_document(db, user, doc) -> bool:
    return can_relax(str(user.id), doc.created_by, await collection_owner_id(db, doc.collection_id))
