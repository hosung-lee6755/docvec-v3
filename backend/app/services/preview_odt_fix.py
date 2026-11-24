"""H2Orestart가 HWP·HWPX를 연 결과(ODT)에서 한컴오피스와 쪽 나눔이 달라지는 두 곳을 고친다(2026-11-23).

1. 빈 머리말·꼬리말. 한글은 머리말·꼬리말 영역 높이(header/footer-offset)만큼만 본문을 비운다. H2Orestart는 그
   높이를 머리말·꼬리말의 최소 높이로 옮기는데, 안에 빈 문단을 넣으므로 LibreOffice는 문단 높이가 더 크면 그만큼
   본문을 더 줄인다. NS-AM 검사 매뉴얼은 높이 0인 꼬리말이 쪽마다 약 32pt를 차지해 서식마다 마지막 줄이 다음
   쪽으로 넘어갔다. 내용이 없는 머리말·꼬리말은 지우고, 그 최소 높이와 간격은 쪽 여백에 더해 본문 높이를 한글과
   같게 둔다.
2. 표 뒤의 빈 문단. 한글에서 표는 문단 안에 글자처럼 들어가므로 그 문단은 표 높이만 차지한다. H2Orestart는 표를
   꺼내 놓고 남은 문단을 빈 줄로 남기는데, 쪽을 거의 채운 표 뒤에서는 이 줄이 다음 쪽으로 밀려 빈 쪽이 생겼다.
   표 바로 뒤의 빈 문단은 높이가 거의 없는 문단 모양으로 바꾼다.

LibreOffice가 쓴 XML을 다시 직렬화하지 않고, 고칠 부분만 정확히 바꾼다. ElementTree로 다시 쓰면 이름공간
접두사가 바뀌어 속성값 안의 접두사(예: text:condition="ooow:...")가 깨질 수 있다.
"""

import copy
import io
import re
import zipfile
from dataclasses import dataclass

from app.core.safe_xml import parse_xml_bytes

_STYLE_NS = "urn:oasis:names:tc:opendocument:xmlns:style:1.0"
_FO_NS = "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"

_KINDS = ("header", "footer")
_MASTER_PAGE_RE = re.compile(r"<style:master-page\b[^>]*?(?:/>|>.*?</style:master-page>)", re.DOTALL)
_PAGE_LAYOUT_RE = re.compile(
    r"<style:page-layout\b(?P<attrs>[^>]*?)(?:/>|>.*?</style:page-layout>)", re.DOTALL
)
_LAYOUT_NAME_RE = re.compile(r'style:page-layout-name="([^"]+)"')
# 내용이 없는 머리말·꼬리말: 안에 빈 문단만 있다(글자, 그림, 필드가 없다). 셋째 묶음은 빈 문자열로도 맞아야
# 역참조(\3)가 된다. 파이썬 re에서 맞지 않은 묶음을 역참조하면 전체가 맞지 않는다. 속성은 게으르게 읽어 자기
# 닫힘 태그(<style:header style:display="false"/>)의 "/"를 삼키지 않게 한다
_HEADER_FOOTER_RE = re.compile(
    r"<style:((header|footer)(-left|-first|))(?P<attrs>\s[^>]*?)?(?:/>|>(?P<inner>.*?)</style:\2\3>)",
    re.DOTALL,
)
_EMPTY_PARAGRAPHS_RE = re.compile(r"^(?:\s*<text:p\b[^>]*/>|\s*<text:p\b[^>]*>\s*</text:p>)*\s*$")
_LENGTH_RE = re.compile(r"^(-?(?:\d+\.?\d*|\.\d+))(in|cm|mm|pt)$")
_POINTS_PER_UNIT = {"in": 72.0, "cm": 72 / 2.54, "mm": 72 / 25.4, "pt": 1.0}
# 머리말은 본문과의 간격을 아래(margin-bottom)에, 꼬리말은 위(margin-top)에 둔다. 지운 높이는 같은 쪽 여백에 더한다
_SPACING_ATTR = {"header": "fo:margin-bottom", "footer": "fo:margin-top"}
_PAGE_MARGIN_ATTR = {"header": "fo:margin-top", "footer": "fo:margin-bottom"}

# 표 바로 뒤의 빈 문단
_TABLE_TAIL_RE = re.compile(r'(</table:table>)(\s*)<text:p text:style-name="(?P<style>[^"]+)"\s*/>')

TABLE_TAIL_STYLE = "HwpTableTail"
_TABLE_TAIL_STYLE_XML = (
    f'<style:style style:name="{TABLE_TAIL_STYLE}" style:family="paragraph">'
    '<style:paragraph-properties fo:margin-top="0in" fo:margin-bottom="0in" fo:line-height="100%"/>'
    '<style:text-properties fo:font-size="1pt" style:font-size-asian="1pt" style:font-size-complex="1pt"/>'
    "</style:style>"
)
_AUTOMATIC_STYLES_OPEN_RE = re.compile(r"<office:automatic-styles\s*/>|<office:automatic-styles>")


@dataclass(frozen=True)
class OdtFixReport:
    removed_headers_footers: int
    shrunk_table_tails: int


def _attr(tag: str, name: str) -> str | None:
    found = re.search(rf'\s{re.escape(name)}="([^"]*)"', tag)
    return found.group(1) if found else None


def _points(length: str | None) -> float | None:
    found = _LENGTH_RE.match(length or "")
    return float(found.group(1)) * _POINTS_PER_UNIT[found.group(2)] if found else None


def _empty_kinds(master_xml: str) -> set[str]:
    """이 마스터 페이지에서 모든 갈래(왼쪽·첫 쪽 포함)가 비어 있는 머리말·꼬리말 종류. 숨긴 갈래
    (style:display="false")가 있으면 그 종류는 자리를 차지하지 않는 것이므로 건드리지 않는다."""
    seen: dict[str, list[bool]] = {kind: [] for kind in _KINDS}
    for match in _HEADER_FOOTER_RE.finditer(master_xml):
        inner = match.group("inner")
        hidden = _attr(match.group("attrs") or "", "style:display") == "false"
        seen[match.group(2)].append(not hidden and (inner is None or bool(_EMPTY_PARAGRAPHS_RE.match(inner))))
    return {kind for kind, flags in seen.items() if flags and all(flags)}


def _reserve_in_margin(layout_xml: str, kind: str) -> str | None:
    """머리말(꼬리말) 최소 높이와 본문과의 간격을 쪽 위(아래) 여백에 더한 쪽 모양. 값을 못 읽으면 None."""
    style = re.search(rf"<style:{kind}-style>.*?</style:{kind}-style>", layout_xml, re.DOTALL)
    props = re.search(r"<style:header-footer-properties\b[^>]*>", style.group(0)) if style else None
    page = re.search(r"<style:page-layout-properties\b[^>]*>", layout_xml)
    if props is None or page is None:
        return None
    height = _attr(props.group(0), "svg:height") or _attr(props.group(0), "fo:min-height") or "0in"
    spacing = _attr(props.group(0), _SPACING_ATTR[kind]) or "0in"
    margin_attr = _PAGE_MARGIN_ATTR[kind]
    margin = _attr(page.group(0), margin_attr)
    values = (_points(height), _points(spacing), _points(margin))
    if margin is None or None in values:
        return None
    total = f"{sum(values) / 72:.4f}in"
    new_page = page.group(0).replace(f'{margin_attr}="{margin}"', f'{margin_attr}="{total}"', 1)
    return layout_xml[: page.start()] + new_page + layout_xml[page.end() :]


def _remove_empty_headers_footers(styles_xml: str) -> tuple[str, int]:
    masters = list(_MASTER_PAGE_RE.finditer(styles_xml))
    layouts = {
        _attr(m.group("attrs"), "style:name"): m
        for m in _PAGE_LAYOUT_RE.finditer(styles_xml)
        if m.group(0).endswith("</style:page-layout>")
    }
    users: dict[str, list[int]] = {}
    empty: list[set[str]] = []
    for index, master in enumerate(masters):
        layout = _LAYOUT_NAME_RE.search(master.group(0))
        if layout:
            users.setdefault(layout.group(1), []).append(index)
        empty.append(_empty_kinds(master.group(0)))

    # 같은 쪽 모양을 쓰는 마스터 페이지가 모두 그 종류를 비워 둘 때만 지운다. 하나라도 내용이 있으면 쪽 여백을
    # 바꿀 수 없다(그 마스터 페이지의 본문 높이까지 바뀐다)
    replacements: list[tuple[int, int, str]] = []
    remove_by_master: dict[int, set[str]] = {}
    for layout_name, indices in users.items():
        layout = layouts.get(layout_name)
        if layout is None:
            continue
        layout_xml = layout.group(0)
        removed_kinds = set()
        for kind in _KINDS:
            if not all(kind in empty[i] for i in indices):
                continue
            adjusted = _reserve_in_margin(layout_xml, kind)
            if adjusted is not None:
                layout_xml = adjusted
                removed_kinds.add(kind)
        if removed_kinds:
            replacements.append((layout.start(), layout.end(), layout_xml))
            for i in indices:
                remove_by_master[i] = removed_kinds

    removed = 0
    for index, kinds in remove_by_master.items():
        master = masters[index]

        def drop(match: re.Match, kinds: set[str] = kinds) -> str:
            nonlocal removed
            if match.group(2) not in kinds:
                return match.group(0)
            removed += 1
            return ""

        replacements.append((master.start(), master.end(), _HEADER_FOOTER_RE.sub(drop, master.group(0))))

    for start, end, new in sorted(replacements, reverse=True):
        styles_xml = styles_xml[:start] + new + styles_xml[end:]
    return styles_xml, removed


def _paragraph_styles(xml: bytes) -> dict[str, tuple[str | None, bool]]:
    """문단 모양 이름 -> (부모 모양 이름, 이 모양 자체가 쪽을 넘기거나 쪽 모양을 바꾸는지)."""
    styles: dict[str, tuple[str | None, bool]] = {}
    for style in parse_xml_bytes(xml).iter(f"{{{_STYLE_NS}}}style"):
        name = style.get(f"{{{_STYLE_NS}}}name")
        if not name:
            continue
        props = style.find(f"{{{_STYLE_NS}}}paragraph-properties")
        breaks = props is not None and (
            props.get(f"{{{_FO_NS}}}break-before", "auto") != "auto"
            or props.get(f"{{{_FO_NS}}}break-after", "auto") != "auto"
        )
        moves = bool(style.get(f"{{{_STYLE_NS}}}master-page-name")) or breaks
        styles[name] = (style.get(f"{{{_STYLE_NS}}}parent-style-name"), moves)
    return styles


def _styles_that_move_pages(content_xml: bytes, styles_xml: bytes) -> set[str]:
    """쪽을 넘기거나 쪽 모양을 바꾸는 문단 모양(부모 모양에서 물려받은 것 포함). 이런 빈 문단은 줄이면 쪽 나눔이
    사라지므로 그대로 둔다. 자동 모양(content.xml)의 부모는 공용 모양(styles.xml)이다."""
    common = _paragraph_styles(styles_xml)
    automatic = _paragraph_styles(content_xml)

    def moves(name: str | None, table: dict, seen: set[str]) -> bool:
        if name is None or name in seen or name not in table:
            return False
        seen.add(name)
        parent, own = table[name]
        return own or moves(parent, common, seen)

    return {name for name in automatic if moves(name, automatic, set())}


def _shrink_table_tails(content_xml: bytes, styles_xml: bytes) -> tuple[bytes, int]:
    keep = _styles_that_move_pages(content_xml, styles_xml)
    text = content_xml.decode("utf-8")
    shrunk = 0

    def replace(match: re.Match) -> str:
        nonlocal shrunk
        if match.group("style") in keep:
            return match.group(0)
        shrunk += 1
        return f'{match.group(1)}{match.group(2)}<text:p text:style-name="{TABLE_TAIL_STYLE}"/>'

    text = _TABLE_TAIL_RE.sub(replace, text)
    if not shrunk:
        return content_xml, 0
    opened = _AUTOMATIC_STYLES_OPEN_RE.search(text)
    if opened is None:
        return content_xml, 0
    tag = opened.group(0)
    styles = (
        f"<office:automatic-styles>{_TABLE_TAIL_STYLE_XML}</office:automatic-styles>"
        if tag.endswith("/>")
        else f"{tag}{_TABLE_TAIL_STYLE_XML}"
    )
    text = text[: opened.start()] + styles + text[opened.end() :]
    return text.encode("utf-8"), shrunk


def fix_hwp_odt(odt: bytes) -> tuple[bytes, OdtFixReport]:
    """ODT를 받아 고친 ODT와 고친 개수를 돌려준다. 고칠 것이 없으면 받은 바이트를 그대로 돌려준다."""
    with zipfile.ZipFile(io.BytesIO(odt)) as zin:
        original_styles = zin.read("styles.xml")
        styles_xml, removed = _remove_empty_headers_footers(original_styles.decode("utf-8"))
        content_xml, shrunk = _shrink_table_tails(zin.read("content.xml"), original_styles)
        report = OdtFixReport(removed_headers_footers=removed, shrunk_table_tails=shrunk)
        if not removed and not shrunk:
            return odt, report
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zout:
            for item in zin.infolist():
                if item.filename == "styles.xml":
                    data = styles_xml.encode("utf-8")
                elif item.filename == "content.xml":
                    data = content_xml
                else:
                    data = zin.read(item)
                # mimetype은 압축하지 않고 맨 앞에 둔다(ODF 규칙). infolist 순서와 압축 방식을 그대로 따른다.
                # writestr 가 ZipInfo 를 고치므로 읽은 쪽 것을 복사해 쓴다
                zout.writestr(copy.copy(item), data, compress_type=item.compress_type)
    return out.getvalue(), report
