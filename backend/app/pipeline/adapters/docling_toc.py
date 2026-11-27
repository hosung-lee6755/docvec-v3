"""Docling 목차(document_index) 항목을 목차 줄로 바꾼다.

Docling 은 PDF 목차를 문단이 아닌 표 형태의 항목(label=document_index)으로 돌려준다. 이 항목은 글을
`text` 속성이 아니라 표 칸에 담기 때문에, 예전에는 목차 노드가 늘 빈 채로 저장됐다(2026-11-20 실측:
기계설비 매뉴얼 등 PDF 5건의 목차 노드 전부). 원본 텍스트 레이어의 글을 먼저 쓰고, 텍스트 레이어가 없는
스캔 PDF 는 Docling 이 읽은 표 칸을 행 단위로 이어 쓴다. 품질 점검이 목차 항목마다 본문 제목과 맞대 볼 수
있게 한 줄을 한 항목으로 나눈다.
"""
import re

TOC_LABELS = frozenset({"document_index"})

# 목차 줄 끝의 점선(.…·ㆍ‥)과 쪽 번호
_PAGE_TAIL_RE = re.compile(r"[.…·ㆍ‥\s]*\d{1,4}\s*$")
# 앞 줄에서 넘어온 점선이나 쪽 번호만 있는 줄
_CONTINUATION_RE = re.compile(r"^[.…·ㆍ‥\s]*\d{0,4}\s*$")
_TOC_TITLES = frozenset({"목차", "차례", "contents", "tableofcontents"})


def _has_page_number(line: str) -> bool:
    return bool(_PAGE_TAIL_RE.search(line)) and not _CONTINUATION_RE.match(line)


def toc_lines(text: str) -> list[str]:
    """목차 글을 항목 줄 목록으로 만든다. "목차" 같은 제목 줄은 이미 제목 노드로 남으므로 뺀다.

    한 항목이 두 줄로 꺾여 점선이나 쪽 번호만 다음 줄로 넘어가면 앞 줄에 붙인다. 붙일 곳이 없는
    번호만 있는 줄(장 표지의 "01" 등)은 버린다."""
    entries: list[str] = []
    for raw in (text or "").splitlines():
        line = " ".join(raw.split())
        if not line or re.sub(r"\s+", "", line).lower() in _TOC_TITLES:
            continue
        if _CONTINUATION_RE.match(line):
            if entries and not _has_page_number(entries[-1]):
                entries[-1] = f"{entries[-1]} {line}"
            continue
        entries.append(line)
    return entries


# 옆 단 차례 줄로 받을 최대 글자 수(본문 줄이 우연히 숫자로 끝나도 차례로 받지 않게)
_SIDE_LINE_MAX_CHARS = 80


def toc_columns(lines: list[list[tuple]], right_edge: float) -> tuple[list[str], list[str]]:
    """화면 줄(낱말 (x0, y0, x1, y1, 글) 목록)을 Docling 차례 영역(오른쪽 끝 right_edge) 안 줄과 옆 단 차례 줄로 나눈다.

    Docling 차례 영역은 오른쪽 끝 쪽 번호 열을 자주 빠뜨려(기계설비 매뉴얼 3쪽) 쪽 너비로 읽는데, 두 단 차례 상자나
    옆 단 본문이 같은 높이에 있으면 서로 다른 단의 글이 한 줄로 섞였다(Pub120bk 490쪽 "Search and Rescue 528
    The terrain is Kharst plateau…", 2026-11-26). 영역 밖 글은 점선·쪽 번호뿐이면 그 줄 끝에 붙이고, "항목 쪽번호"
    모양이면 옆 단 차례 줄로 따로 모으고(왼쪽 단 다음에 적는다), 그 밖의 글(옆 단 본문)은 버린다."""
    main: list[str] = []
    side: list[str] = []
    for line in lines:
        inside = " ".join(word[4] for word in line if word[0] < right_edge)
        outside = " ".join(word[4] for word in line if word[0] >= right_edge)
        if outside and _CONTINUATION_RE.match(outside):
            inside = f"{inside} {outside}".strip()
        elif (
            outside and _has_page_number(outside) and len(outside) <= _SIDE_LINE_MAX_CHARS
            and any(char.isalpha() for char in outside)
        ):
            side.append(outside)
        if inside:
            main.append(inside)
    return main, side


def choose_toc_lines(native_text: str, cell_text: str) -> list[str]:
    """원본 글에 쪽 번호가 붙은 목차 줄이 하나라도 있으면 원본 글을, 아니면 Docling 표 칸 글을 쓴다.

    스캔 PDF 의 텍스트 레이어에 워터마크·쪽 번호 몇 글자만 남은 경우 원본 글을 쓰면 목차가 그 몇 글자가 된다."""
    native = toc_lines(native_text)
    if any(_has_page_number(line) for line in native):
        return native
    cells = toc_lines(cell_text)
    return cells or native


def grid_text(rows: list[list[str]]) -> str:
    """표 칸으로 읽힌 목차를 행마다 한 줄로 잇는다(텍스트 레이어가 없는 스캔 PDF 용)."""
    lines = (" ".join(cell.strip() for cell in row if cell and cell.strip()) for row in rows)
    return "\n".join(line for line in lines if line)
