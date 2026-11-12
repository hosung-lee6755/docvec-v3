import io
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.v1.deps import get_current_user, require_admin
from app.db.models.dictionary_application import DictionaryApplication
from app.db.models.dictionary_entry import DictionaryEntry
from app.db.models.dictionary_entry_variant import DictionaryEntryVariant
from app.db.models.dictionary_revision import DictionaryRevision
from app.db.models.document import Document
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.dictionary import (
    DictionaryEntryCreate,
    DictionaryEntryListResponse,
    DictionaryEntryResponse,
    DictionaryEntryType,
    DictionaryEntryUpdate,
    DictionaryImpactDocument,
    DictionaryImpactResponse,
    DictionaryImportResult,
    DictionaryRevisionItem,
    DictionaryRevisionsResponse,
)
from app.services.dictionary_service import bump_revision, refresh_dictionary_cache

# 버전 이력 탭이 한 번에 보여줄 최대 리비전 수 — 사전 크기는 작지만 리비전은
# 시간이 지날수록 누적되므로 무제한 조회를 막는다.
_MAX_REVISIONS = 200

router = APIRouter()

# Admin-only bulk import — bounded so a malformed/huge spreadsheet can't tie up
# a request indefinitely. Dictionary sizes are inherently small (hand-curated
# stopword/synonym/custom-word lists), so this is far above any real use.
_MAX_IMPORT_ROWS = 5000

# Excel column headers per entry type — matches 문서_처리_사전_스키마.md §6.
_EXPORT_COLUMNS: dict[str, list[str]] = {
    "stopword": ["단어", "일치방식", "대소문자구분", "언어", "적용범위", "제외사유", "사용여부"],
    "synonym": ["대표용어", "동의어", "적용방향", "처리방식", "대소문자구분", "언어", "적용범위", "사용여부"],
    "custom_word": [
        "표준용어", "변형표현", "용어유형", "처리규칙", "정의",
        "대소문자구분", "언어", "적용범위", "사용여부", "발음",
    ],
}

# Column-by-column reference for the "스키마 안내" sheet: (컬럼명, 설명, 필수여부, 허용값/형식, 예시).
# Descriptions/examples mirror 문서_처리_사전_스키마.md §1-3.
_FIELD_GUIDES: dict[str, list[tuple[str, str, str, str, str]]] = {
    "stopword": [
        ("단어", "제외할 단어 또는 표현", "필수", "텍스트", "그리고"),
        ("일치방식", "단어 일치 판정 방식", "필수(기본 EXACT)", "EXACT / CONTAINS / PREFIX / SUFFIX / REGEX", "EXACT"),
        ("대소문자구분", "영문 대소문자 구분 여부", "선택(기본 N)", "Y 또는 N", "N"),
        ("언어", "언어 코드", "선택(기본 ko)", "언어 코드", "ko"),
        ("적용범위", "적용 문서 유형/업무 범위. 여러 개는 세미콜론(;)으로 구분", "선택(기본 ALL)", "텍스트(;로 구분)", "ALL"),
        ("제외사유", "제외 사유", "선택", "텍스트", "접속사"),
        ("사용여부", "사용 여부", "필수", "Y 또는 N", "Y"),
    ],
    "synonym": [
        ("대표용어", "대표 용어", "필수", "텍스트", "인공지능"),
        ("동의어", "동의어 및 변형 표현. 최소 1개 필수, 여러 개는 세미콜론(;)으로 구분", "필수", "텍스트(;로 구분)", "AI;A.I.;인공 지능"),
        ("적용방향", "동의어 적용 방향", "필수(기본 ONE_WAY)", "ONE_WAY / BIDIRECTIONAL", "ONE_WAY"),
        ("처리방식", "동의어 처리 방식", "필수(기본 NORMALIZE)", "NORMALIZE / REPLACE / SEARCH_EXPAND / TAGGING", "NORMALIZE"),
        ("대소문자구분", "영문 대소문자 구분 여부", "선택(기본 N)", "Y 또는 N", "N"),
        ("언어", "언어 코드", "선택(기본 ko)", "언어 코드", "ko"),
        ("적용범위", "적용 범위. 여러 개는 세미콜론(;)으로 구분", "선택(기본 ALL)", "텍스트(;로 구분)", "ALL"),
        ("사용여부", "사용 여부", "필수", "Y 또는 N", "Y"),
    ],
    "custom_word": [
        ("표준용어", "표준 용어", "필수", "텍스트", "LangGraph"),
        ("변형표현", "오탈자, 띄어쓰기, 별칭 등. 여러 개는 세미콜론(;)으로 구분", "선택", "텍스트(;로 구분)", "랭그래프;Lang Graph"),
        ("용어유형", "용어 유형", "필수(기본 CUSTOM)",
         "TECHNICAL_TERM / ABBREVIATION / ORGANIZATION / PERSON / PRODUCT / PROJECT / POLICY / CUSTOM", "PRODUCT"),
        ("처리규칙", "처리 규칙", "필수(기본 KEEP)", "KEEP / NORMALIZE / REPLACE / TAG / EXTRACT / MASK / IGNORE", "KEEP"),
        ("정의", "용어 정의", "선택", "텍스트", "그래프 기반 AI 워크플로우 프레임워크"),
        ("대소문자구분", "대소문자 구분 여부", "선택(기본 N)", "Y 또는 N", "Y"),
        ("언어", "언어 코드", "선택(기본 ko)", "언어 코드", "en"),
        ("적용범위", "적용 범위. 여러 개는 세미콜론(;)으로 구분", "선택(기본 ALL)", "텍스트(;로 구분)", "요구사항 정의서;기술 설계서"),
        ("사용여부", "사용 여부", "필수", "Y 또는 N", "Y"),
        ("발음", "발음 또는 읽기 정보", "선택", "텍스트", "랭그래프"),
    ],
}

# Filled-in example rows matching 문서_처리_사전_스키마.md §1-3's JSON examples,
# in the same column order as _EXPORT_COLUMNS — copy/edit these rows directly.
_EXAMPLE_ROWS: dict[str, list[tuple]] = {
    "stopword": [("그리고", "EXACT", "N", "ko", "ALL", "접속사", "Y")],
    "synonym": [("인공지능", "AI;A.I.;인공 지능;Artificial Intelligence", "ONE_WAY", "NORMALIZE", "N", "ko", "ALL", "Y")],
    "custom_word": [(
        "LangGraph", "랭그래프;Lang Graph", "PRODUCT", "KEEP",
        "그래프 기반 AI 에이전트 및 워크플로우 구성 프레임워크", "Y", "en", "요구사항 정의서;기술 설계서", "Y", "랭그래프",
    )],
}

# Enum reference for the "스키마 안내" sheet: (필드명, 값, 설명). Processing
# modes/rules beyond NORMALIZE/KEEP are stored but not yet applied at
# tokenize time — flagged here so the sheet doesn't overstate what happens.
_ENUM_GUIDES: dict[str, list[tuple[str, str, str]]] = {
    "stopword": [
        ("일치방식", "EXACT", "단어가 정확히 일치할 때 제외"),
        ("일치방식", "CONTAINS", "해당 문자열을 포함하면 제외"),
        ("일치방식", "PREFIX", "해당 문자열로 시작하면 제외"),
        ("일치방식", "SUFFIX", "해당 문자열로 끝나면 제외"),
        ("일치방식", "REGEX", "정규식 기준으로 제외"),
    ],
    "synonym": [
        ("적용방향", "ONE_WAY", "동의어를 대표 용어로만 변환"),
        ("적용방향", "BIDIRECTIONAL", "그룹 내 모든 용어를 서로 동의어로 인식"),
        ("처리방식", "NORMALIZE", "내부 분석 시 대표 용어로 통합 — 검색에 실제 적용됨"),
        ("처리방식", "REPLACE", "문서 텍스트를 대표 용어로 치환 — 현재는 값만 저장, 검색에는 아직 미적용"),
        ("처리방식", "SEARCH_EXPAND", "검색 시 동의어를 함께 검색 — 현재는 값만 저장, 검색에는 아직 미적용"),
        ("처리방식", "TAGGING", "동일 개념 태그 부여 — 현재는 값만 저장, 검색에는 아직 미적용"),
    ],
    "custom_word": [
        ("용어유형", "TECHNICAL_TERM", "전문용어"),
        ("용어유형", "ABBREVIATION", "약어"),
        ("용어유형", "ORGANIZATION", "기관명"),
        ("용어유형", "PERSON", "인명"),
        ("용어유형", "PRODUCT", "제품 또는 서비스명"),
        ("용어유형", "PROJECT", "프로젝트명"),
        ("용어유형", "POLICY", "정책 또는 제도명"),
        ("용어유형", "CUSTOM", "사용자 정의 유형"),
        ("처리규칙", "KEEP", "원문 유지 — 검색에 실제 적용됨"),
        ("처리규칙", "NORMALIZE", "변형 표현을 표준 용어로 인식 — 검색에 실제 적용됨"),
        ("처리규칙", "REPLACE", "실제 텍스트 치환 — 현재는 값만 저장, 검색에는 아직 미적용"),
        ("처리규칙", "TAG", "용어 유형 태그 부여 — 현재는 값만 저장, 검색에는 아직 미적용"),
        ("처리규칙", "EXTRACT", "주요 개체로 추출 — 현재는 값만 저장, 검색에는 아직 미적용"),
        ("처리규칙", "MASK", "민감정보 마스킹 — 현재는 값만 저장, 검색에는 아직 미적용"),
        ("처리규칙", "IGNORE", "처리 대상에서 제외 (사전에 등록하지 않음)"),
    ],
}


def _write_guide_sheet(wb: Workbook, entry_type: str) -> None:
    """Adds a "스키마 안내" reference sheet after the data sheet so the
    downloaded file is self-explanatory when a user fills it in by hand.
    Does not touch wb.active — the data sheet (index 0) stays active so
    import_dictionary_entries keeps reading the right sheet."""
    ws = wb.create_sheet(title="스키마 안내")
    ws.append(["컬럼 설명"])
    ws.append(["컬럼명", "설명", "필수여부", "허용값/형식", "예시"])
    for guide_row in _FIELD_GUIDES[entry_type]:
        ws.append(list(guide_row))

    ws.append([])
    ws.append(["작성 예시 (이 행을 복사해서 값을 바꿔 사용하세요)"])
    ws.append(_EXPORT_COLUMNS[entry_type])
    for example_row in _EXAMPLE_ROWS[entry_type]:
        ws.append(list(example_row))

    ws.append([])
    ws.append(["코드 값 참고"])
    ws.append(["필드명", "값", "설명"])
    for enum_row in _ENUM_GUIDES[entry_type]:
        ws.append(list(enum_row))

    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 48
    ws.column_dimensions["C"].width = 16
    ws.column_dimensions["D"].width = 40
    ws.column_dimensions["E"].width = 28


def _serialize(entry: DictionaryEntry) -> DictionaryEntryResponse:
    return DictionaryEntryResponse(
        id=entry.id,
        entry_type=entry.entry_type,
        term=entry.term,
        variants=[v.variant_term for v in entry.variants],
        match_type=entry.match_type,
        direction=entry.direction,
        processing_mode=entry.processing_mode,
        term_type=entry.term_type,
        processing_rule=entry.processing_rule,
        pronunciation=entry.pronunciation,
        case_sensitive=entry.case_sensitive,
        language=entry.language,
        scope=entry.scope or [],
        description=entry.description,
        enabled=entry.enabled,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _apply_variants(entry: DictionaryEntry, variants: list[str]) -> None:
    entry.variants.clear()
    for i, variant_term in enumerate(variants):
        entry.variants.append(DictionaryEntryVariant(variant_term=variant_term, sort_order=i))


async def _dictionary_changed(db: AsyncSession, schedule_eval: bool = True) -> None:
    """사전이 바뀌면 캐시를 다시 읽고, 골든쿼리가 있는 컬렉션의 평가를 예약한다(v3 마일스톤 7).
    검색어 확장과 키워드 검색이 바로 달라지기 때문이다. 예약이 실패해도 사전 변경은 유지된다."""
    import logging

    from app.services.golden_eval import schedule_for_all_collections

    await refresh_dictionary_cache(db)
    if not schedule_eval:
        return
    try:
        await schedule_for_all_collections(db, "dictionary")
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("golden eval scheduling after dictionary change failed", exc_info=True)


@router.post("/admin/dictionary", response_model=DictionaryEntryResponse)
async def create_dictionary_entry(
    data: DictionaryEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    entry_id = str(uuid4())
    entry = DictionaryEntry(
        id=entry_id,
        entry_type=data.entry_type,
        term=data.term,
        match_type=data.match_type,
        direction=data.direction,
        processing_mode=data.processing_mode,
        term_type=data.term_type,
        processing_rule=data.processing_rule,
        pronunciation=data.pronunciation,
        case_sensitive=data.case_sensitive,
        language=data.language,
        scope=data.scope,
        description=data.description,
        enabled=data.enabled,
        created_by=str(current_user.id),
        variants=[
            DictionaryEntryVariant(variant_term=v, sort_order=i)
            for i, v in enumerate(data.variants)
        ],
    )
    db.add(entry)
    await bump_revision(db, entry_id, "CREATE", str(current_user.id))
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="해당 유형/용어의 사전 항목이 이미 존재합니다"
        )
    # With expire_on_commit=False, objects remain cached after commit, but
    # relationships are still not refreshed by db.refresh(). To ensure
    # `variants` is populated for _serialize() without async-unsafe lazy load,
    # re-fetch with selectinload instead, same idiom as
    # list_dictionary_entries/update_dictionary_entry's initial query.
    entry = await db.scalar(
        select(DictionaryEntry)
        .where(DictionaryEntry.id == entry_id)
        .options(selectinload(DictionaryEntry.variants))
    )
    await _dictionary_changed(db)
    return _serialize(entry)


@router.get("/admin/dictionary", response_model=DictionaryEntryListResponse)
async def list_dictionary_entries(
    entry_type: DictionaryEntryType | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    query = (
        select(DictionaryEntry)
        .options(selectinload(DictionaryEntry.variants))
        .order_by(DictionaryEntry.created_at.desc())
    )
    if entry_type is not None:
        query = query.where(DictionaryEntry.entry_type == entry_type)
    rows = (await db.scalars(query)).all()
    return {"items": [_serialize(row) for row in rows]}


@router.patch("/admin/dictionary/{entry_id}", response_model=DictionaryEntryResponse)
async def update_dictionary_entry(
    entry_id: UUID,
    data: DictionaryEntryUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    entry = await db.scalar(
        select(DictionaryEntry)
        .where(DictionaryEntry.id == str(entry_id))
        .options(selectinload(DictionaryEntry.variants))
    )
    if not entry:
        raise HTTPException(status_code=404, detail="사전 항목을 찾을 수 없습니다")

    updates = data.model_dump(exclude_unset=True, exclude={"variants"})
    for field, field_value in updates.items():
        setattr(entry, field, field_value)
    if data.variants is not None:
        _apply_variants(entry, data.variants)

    await bump_revision(db, str(entry.id), "UPDATE", str(current_user.id))
    entry_id_str = str(entry.id)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="해당 유형/용어의 사전 항목이 이미 존재합니다"
        )
    # Same MissingGreenlet pitfall as create_dictionary_entry — re-fetch with
    # selectinload instead of refresh() to get `variants` back in a loaded state.
    entry = await db.scalar(
        select(DictionaryEntry)
        .where(DictionaryEntry.id == entry_id_str)
        .options(selectinload(DictionaryEntry.variants))
    )
    await _dictionary_changed(db)
    return _serialize(entry)


@router.delete("/admin/dictionary/{entry_id}", status_code=204)
async def delete_dictionary_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    entry = await db.scalar(select(DictionaryEntry).where(DictionaryEntry.id == str(entry_id)))
    if not entry:
        raise HTTPException(status_code=404, detail="사전 항목을 찾을 수 없습니다")
    # Revision row must be inserted (FK still valid) before the entry is
    # deleted — the FK's ondelete="SET NULL" then nullifies it automatically.
    await bump_revision(db, str(entry.id), "DELETE", str(current_user.id))
    await db.flush()
    await db.delete(entry)
    await db.commit()
    await _dictionary_changed(db)


@router.get("/admin/dictionary/entries/{entry_id}/impact", response_model=DictionaryImpactResponse)
async def get_dictionary_entry_impact(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """사전 항목 저장 시 "영향 문서 N건" 다이얼로그가 쓰는 미리보기 —
    이 항목이 (취소되지 않은 채) 적용된 문서 목록을 반환한다. 통합 설계서 §8."""
    require_admin(current_user)
    rows = (
        await db.execute(
            select(Document.id, Document.original_filename)
            .join(DictionaryApplication, DictionaryApplication.document_id == Document.id)
            .where(
                DictionaryApplication.entry_id == entry_id,
                DictionaryApplication.reverted.is_(False),
            )
            .distinct()
        )
    ).all()
    documents = [DictionaryImpactDocument(id=row.id, filename=row.original_filename) for row in rows]
    return DictionaryImpactResponse(
        entry_id=entry_id, affected_document_count=len(documents), documents=documents,
    )


@router.get("/admin/dictionary/revisions", response_model=DictionaryRevisionsResponse)
async def list_dictionary_revisions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """사전 화면의 "버전 이력" 탭 — 누가/언제/무엇을(add/edit/delete/import) 했는지만
    보여준다. DictionaryRevision은 필드 단위 이전/이후 값(diff)을 저장하지 않으므로
    값 변경 내역까지는 표시하지 않는 축소 스코프(통합 설계서 §8)."""
    require_admin(current_user)
    rows = (
        await db.execute(
            select(
                DictionaryRevision.version,
                DictionaryRevision.changed_entry_id,
                DictionaryEntry.term,
                DictionaryEntry.entry_type,
                DictionaryRevision.change_type,
                DictionaryRevision.created_by,
                User.username,
                DictionaryRevision.created_at,
            )
            .outerjoin(DictionaryEntry, DictionaryEntry.id == DictionaryRevision.changed_entry_id)
            .outerjoin(User, User.id == DictionaryRevision.created_by)
            .order_by(DictionaryRevision.version.desc())
            .limit(_MAX_REVISIONS)
        )
    ).all()
    return DictionaryRevisionsResponse(
        revisions=[
            DictionaryRevisionItem(
                version=row.version,
                changed_entry_id=row.changed_entry_id,
                entry_term=row.term,
                entry_type=row.entry_type,
                change_type=row.change_type,
                created_by=row.created_by,
                created_by_name=row.username,
                created_at=row.created_at,
            )
            for row in rows
        ]
    )


def _bool_to_yn(value: bool) -> str:
    return "Y" if value else "N"


def _yn_to_bool(value, default: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().upper() in ("Y", "YES", "TRUE", "1")


def _join_list(values: list[str], sep: str) -> str:
    return sep.join(values or [])


def _split_list(raw, sep: str, default: list[str] | None = None) -> list[str]:
    if raw is None or str(raw).strip() == "":
        return list(default or [])
    return [v.strip() for v in str(raw).split(sep) if v.strip()]


def _cell(row: tuple, index: int) -> str | None:
    if not row or len(row) <= index or row[index] is None:
        return None
    return str(row[index]).strip() or None


def _export_row(entry_type: str, entry: DictionaryEntry) -> list:
    variants = _join_list([v.variant_term for v in entry.variants], ";")
    scope = _join_list(entry.scope or [], ",")
    if entry_type == "stopword":
        return [
            entry.term, entry.match_type or "EXACT", _bool_to_yn(entry.case_sensitive),
            entry.language, scope, entry.description or "", _bool_to_yn(entry.enabled),
        ]
    if entry_type == "synonym":
        return [
            entry.term, variants, entry.direction or "ONE_WAY", entry.processing_mode or "NORMALIZE",
            _bool_to_yn(entry.case_sensitive), entry.language, scope, _bool_to_yn(entry.enabled),
        ]
    return [
        entry.term, variants, entry.term_type or "CUSTOM", entry.processing_rule or "KEEP",
        entry.description or "", _bool_to_yn(entry.case_sensitive), entry.language, scope,
        _bool_to_yn(entry.enabled), entry.pronunciation or "",
    ]


def _parse_import_row(entry_type: str, row: tuple) -> dict | None:
    """Returns a dict of DictionaryEntry field values parsed from one Excel
    row, or None if the row has no usable data (blank, or missing a
    type-required field like the term or a synonym's variant list)."""
    term = _cell(row, 0)
    if entry_type == "stopword":
        if not term:
            return None
        return {
            "term": term,
            "variants": [],
            "match_type": (_cell(row, 1) or "EXACT").upper(),
            "case_sensitive": _yn_to_bool(_cell(row, 2)),
            "language": _cell(row, 3) or "ko",
            "scope": _split_list(_cell(row, 4), ",", ["ALL"]),
            "description": _cell(row, 5),
            "enabled": _yn_to_bool(_cell(row, 6), default=True),
        }
    if entry_type == "synonym":
        variants = _split_list(_cell(row, 1), ";")
        if not term or not variants:
            return None
        return {
            "term": term,
            "variants": variants,
            "direction": (_cell(row, 2) or "ONE_WAY").upper(),
            "processing_mode": (_cell(row, 3) or "NORMALIZE").upper(),
            "case_sensitive": _yn_to_bool(_cell(row, 4)),
            "language": _cell(row, 5) or "ko",
            "scope": _split_list(_cell(row, 6), ",", ["ALL"]),
            "enabled": _yn_to_bool(_cell(row, 7), default=True),
        }
    # custom_word
    if not term:
        return None
    return {
        "term": term,
        "variants": _split_list(_cell(row, 1), ";"),
        "term_type": (_cell(row, 2) or "CUSTOM").upper(),
        "processing_rule": (_cell(row, 3) or "KEEP").upper(),
        "description": _cell(row, 4),
        "case_sensitive": _yn_to_bool(_cell(row, 5)),
        "language": _cell(row, 6) or "ko",
        "scope": _split_list(_cell(row, 7), ",", ["ALL"]),
        "enabled": _yn_to_bool(_cell(row, 8), default=True),
        "pronunciation": _cell(row, 9),
    }


@router.get("/admin/dictionary/export")
async def export_dictionary_entries(
    entry_type: DictionaryEntryType,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_admin(current_user)
    rows = (
        await db.scalars(
            select(DictionaryEntry)
            .where(DictionaryEntry.entry_type == entry_type)
            .options(selectinload(DictionaryEntry.variants))
            .order_by(DictionaryEntry.term)
        )
    ).all()

    wb = Workbook()
    ws = wb.active
    ws.title = entry_type
    ws.append(_EXPORT_COLUMNS[entry_type])
    for row in rows:
        ws.append(_export_row(entry_type, row))
    _write_guide_sheet(wb, entry_type)

    buffer = io.BytesIO()
    wb.save(buffer)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="dictionary_{entry_type}.xlsx"'},
    )


@router.post("/admin/dictionary/import", response_model=DictionaryImportResult)
async def import_dictionary_entries(
    entry_type: DictionaryEntryType,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upserts by (entry_type, term). Column layout follows
    문서_처리_사전_스키마.md §6 and differs per entry_type — see
    _EXPORT_COLUMNS/_parse_import_row. Rows missing a required field are
    skipped and reported rather than failing the whole import."""
    require_admin(current_user)
    contents = await file.read()
    try:
        wb = load_workbook(io.BytesIO(contents), read_only=True, data_only=True)
        ws = wb.active
    except Exception:
        raise HTTPException(status_code=400, detail="유효한 엑셀(.xlsx) 파일이 아닙니다")

    # Read one row past the cap so an over-limit file is detected rather than
    # silently truncated.
    raw_rows = list(ws.iter_rows(min_row=2, max_row=_MAX_IMPORT_ROWS + 2, values_only=True))
    if len(raw_rows) > _MAX_IMPORT_ROWS:
        raise HTTPException(
            status_code=400, detail=f"한 번에 최대 {_MAX_IMPORT_ROWS}행까지 가져올 수 있습니다"
        )

    existing = {
        entry.term: entry
        for entry in (
            await db.scalars(
                select(DictionaryEntry)
                .where(DictionaryEntry.entry_type == entry_type)
                .options(selectinload(DictionaryEntry.variants))
            )
        ).all()
    }

    created = updated = skipped = 0
    skipped_rows: list[int] = []
    for row_number, raw_row in enumerate(raw_rows, start=2):
        if not any(_cell(raw_row, i) for i in range(len(raw_row or ()))):
            continue  # blank trailing row — not worth reporting

        parsed = _parse_import_row(entry_type, raw_row)
        if parsed is None:
            skipped += 1
            skipped_rows.append(row_number)
            continue

        variants = parsed.pop("variants")
        term = parsed["term"]
        if term in existing:
            entry = existing[term]
            for field, field_value in parsed.items():
                setattr(entry, field, field_value)
            _apply_variants(entry, variants)
            updated += 1
        else:
            entry = DictionaryEntry(
                entry_type=entry_type,
                created_by=str(current_user.id),
                **parsed,
            )
            entry.variants = [
                DictionaryEntryVariant(variant_term=v, sort_order=i)
                for i, v in enumerate(variants)
            ]
            db.add(entry)
            created += 1

    if created or updated:
        await bump_revision(db, None, "IMPORT", str(current_user.id))
    await db.commit()
    await _dictionary_changed(db, schedule_eval=bool(created or updated))
    return DictionaryImportResult(
        created=created, updated=updated, skipped=skipped, skipped_rows=skipped_rows
    )
