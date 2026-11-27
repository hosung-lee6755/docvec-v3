"""Docling 글의 띄어쓰기를 원본 PDF 글자 층과 견줘 덜 깨진 쪽을 고른다(2026-11-20 감사).

Docling 은 글꼴 정보가 없는 PDF 에서 낱말 중간을 띄우거나("첨 단간 : 텅레 일의 작 동을", KR S-03010 선로전환기)
영어 첫 글자를 떼었다("V oluntary", Pub120bk). 원본 글자 층(pdfplumber)은 글자 사이 거리로 공백을 정해 이런
문서를 바르게 읽지만, 거꾸로 낱말을 붙여 읽는 PDF 도 있다(개인하수처리시설 사례집). 그래서 두 글의 글자가 같을
때만 덜 깨진 쪽을 고르고, 글자가 다르면(영역이 어긋나 옆 글이 섞이는 등) Docling 글을 그대로 둔다.
기호와 숫자를 다른 글꼴로 쓴 PDF 에서는 Docling 이 마침표·괄호·숫자를 옮기거나 빠뜨린다(세원화성 에너지진단보고서).
한글이 같은 순서로 모두 같고 원본이 숫자·기호만 더하거나 바로잡을 때는 원본 글을 쓴다.
"""
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path

from app.pipeline.adapters.symbol_fonts import is_symbol_code, symbol_char, symbol_font_kind

# 한 글자짜리 한글 토막. 자연스러운 글에도 "수", "및"이 있지만 같은 글자의 두 글을 견줄 때만 쓰므로 상대 비교다
_SINGLE_HANGUL_RE = re.compile(r"[가-힣]")
# 이만큼 이어진 한글 덩어리는 낱말이 붙은 것으로 본다
_MERGED_HANGUL_RUN = 10
_MERGED_HANGUL_RE = re.compile(r"[가-힣]{%d,}" % _MERGED_HANGUL_RUN)
# 영어 낱말의 첫 대문자가 떨어진 모양("V oluntary")
_SPLIT_CAPITAL_RE = re.compile(r"(?<![A-Za-z])[A-Z] [a-z]{2,}")
# Docling 이 목록 번호를 떼어 낸 경우 원본 글 앞에만 남는 번호 모양
_LIST_MARKER_RE = re.compile(r"[(\[]?(?:\d{1,3}|[가-하]|[a-zA-Z])[)\].]|[①-⑳]|[•·\-*ㅇ○●■□◦▪]")
# 숫자·기호 복원 규칙은 한글이 이만큼은 있어야 쓴다(영문 글은 이 규칙으로 고치지 않는다)
_MIN_REPAIR_HANGUL = 2
# 원본 글이 더할 수 있는 글자 수의 하한. 그 위로는 Docling 글 길이만큼까지 허용한다
_MIN_REPAIR_ALLOWANCE = 8
# 유니코드 사용자 정의 영역. 수식 글꼴 기호가 이 영역 글리프로 들어온다
_PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")
# 영문 뒤에 붙은 숫자(CO2, H2O). 원본 글자 층은 아래첨자 숫자를 줄 뒤로 보내므로 원본에도 그대로 있어야 한다
_LETTER_DIGIT_RE = re.compile(r"[A-Za-z]+\d+")
# Docling 이 글을 조립하며 바꿔 적는 글자(docling page_assemble_model.sanitize_text). 원본 글과 견줄 때 원본에도
# 같이 적용하고, 저장할 글에는 원본 글자를 되돌린다(2026-11-26, 사례집 "•" 가 "·" 로 저장됨)
_DOCLING_SANITIZED = str.maketrans({"⁄": "/", "’": "'", "‘": "'", "“": '"', "”": '"', "•": "·"})
# 기준선에서 글자 윗변까지를 글꼴 크기의 이 비율로 잡는다(pdfplumber 의 글자 높이와 맞춘 어림값)
_ASCENT_RATIO = 0.8
# 영역 테두리에 걸친 글자를 놓치지 않을 여유(pt)
_REGION_PAD = 2.0
# 겹쳐 그린 글자를 같은 자리로 볼 때의 좌표 단위(pt)
_DUPLICATE_GLYPH_STEP = 0.5


def _rounded(value: float) -> float:
    return round(value / _DUPLICATE_GLYPH_STEP) * _DUPLICATE_GLYPH_STEP


# 쪽 글자 가운데 겹쳐 그린 글자가 이보다 많으면 두 겹 글자층 쪽으로 본다. 휴직규정은 45~47%, 다른 PDF 는 0%였다
DUPLICATE_LAYER_SHARE = 0.2


def _hangul(text: str) -> str:
    return "".join(ch for ch in text if "가" <= ch <= "힣")


def _is_subsequence(part: str, whole: str) -> bool:
    letters = iter(whole)
    return all(ch in letters for ch in part)


def prefer_native_on_duplicate_layer(docling_text: str, native_text: str) -> str:
    """두 겹 글자층 쪽의 글. Docling 은 한 겹(한글만)을 읽어 숫자와 괄호를 옮기고 따옴표를 바꿔 적는다
    ("제 조 적용범위 2 ( ) … 직원 이라"). 원본 글이 Docling 의 한글을 순서대로 다 담고 있으면 원본 글을 쓴다(2026-11-27)."""
    native_flat = " ".join(native_text.split())
    docling_hangul = _hangul(docling_text)
    if native_flat and docling_hangul and _is_subsequence(docling_hangul, _hangul(native_flat)):
        return native_flat
    return docling_text


# Docling 에만 있는 기호가 이만큼 넘으면 글리프를 잘못 옮긴 것으로 본다. 기호 한두 개는 원본 쪽 누락일 수 있다
_PHANTOM_SYMBOL_MIN = 3


def _has_phantom_symbols(docling_text: str, native_flat: str) -> bool:
    """한글은 순서까지 같은데 Docling 글에 원본에 한 번도 없는 기호가 여러 개 끼었는지.

    한컴 글꼴로 만든 PDF 에서 Docling 이 띄어쓰기를 "'"로, 따옴표 “ ”를 NKo 문자(߫ ߬)로 읽었다
    ("이' 시행내규는' 임금피크제'", 임금피크제시행내규 2,269자 중 276곳, 2026-11-27). 원본 글자층은 정상이었다."""
    docling_hangul = _hangul(docling_text)
    if not docling_hangul or docling_hangul != _hangul(native_flat):
        return False
    native_symbols = set(native_flat)
    phantom = [
        ch for ch in docling_text
        if not ch.isspace() and not ch.isalnum() and ch not in native_symbols
    ]
    return len(phantom) >= _PHANTOM_SYMBOL_MIN


def spacing_score(text: str) -> int:
    """띄어쓰기가 깨진 정도. 작을수록 자연스럽다."""
    tokens = text.split()
    singles = sum(1 for token in tokens if _SINGLE_HANGUL_RE.fullmatch(token))
    merged = 2 * len(_MERGED_HANGUL_RE.findall(text))
    split_capitals = len(_SPLIT_CAPITAL_RE.findall(text))
    return singles + merged + split_capitals


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def _restores_symbols(docling_chars: str, native_chars: str) -> bool:
    """원본 글이 Docling 글의 한글을 같은 순서로 모두 담고, 그 밖에 숫자·기호·영문만 더하거나 자리를 바로잡았는지.

    기호와 숫자를 다른 글꼴로 쓴 PDF 에서 Docling 이 마침표·괄호를 뒤로 옮기고("가 에너지원별 사용량 .") 숫자를
    빠뜨렸다("2대(75HP/1, 30HP/1)가" → "대 가", 세원화성 에너지진단보고서 2026-11-20). 영역이 어긋나 옆 글이
    섞이면 한글이 늘거나 순서가 바뀌므로 그때는 고치지 않는다."""
    if _PRIVATE_USE_RE.search(docling_chars) or _PRIVATE_USE_RE.search(native_chars):
        return False  # 수식 글꼴 글리프는 원본 글자 층이 아래첨자를 줄 끝으로 옮긴다(기계설비 매뉴얼)
    docling_hangul = "".join(_SINGLE_HANGUL_RE.findall(docling_chars))
    if len(docling_hangul) < _MIN_REPAIR_HANGUL or docling_hangul != "".join(_SINGLE_HANGUL_RE.findall(native_chars)):
        return False
    extra = Counter(native_chars)
    extra.subtract(Counter(docling_chars))
    if any(count < 0 for count in extra.values()):
        return False  # Docling 에만 있는 글자가 있다
    if any(token not in native_chars for token in _LETTER_DIGIT_RE.findall(docling_chars)):
        return False
    added = sum(extra.values())
    return added <= max(_MIN_REPAIR_ALLOWANCE, len(docling_chars))


def _as_docling_writes(text: str) -> str:
    return text.translate(_DOCLING_SANITIZED)


def _is_plain_symbol(ch: str) -> bool:
    return not ch.isalnum() and ch.isprintable() and not _PRIVATE_USE_RE.match(ch)


def _differs_only_in_symbols(a: str, b: str) -> bool:
    return len(a) == len(b) and all(x == y or (_is_plain_symbol(x) and _is_plain_symbol(y)) for x, y in zip(a, b))


def _docling_view(docling_chars: str, native_chars: str) -> str:
    """원본 글을 Docling 이 적는 글자로 맞춘 글. Docling 글과 견줄 때 쓴다.

    Docling 은 글을 조립하며 "•" 를 "·" 로, 둥근 따옴표를 곧은 따옴표로 바꾸고(sanitize_text), docling-parse 는
    "—" 를 "-" 로 읽는다(Pub120bk). 원본 끝부분(목록 기호 뒤)이 Docling 글과 기호 자리만 다르면 같은 글로 본다."""
    view = _as_docling_writes(native_chars)
    cut = len(view) - len(docling_chars)
    if cut >= 0 and _differs_only_in_symbols(view[cut:], docling_chars):
        view = view[:cut] + docling_chars
    return view


def _with_native_chars(text: str, native_chars: str) -> str:
    """text 의 공백 아닌 글자를 같은 자리의 원본 글자로 바꾼다. 글자 수가 다르면 그대로 둔다."""
    text = unicodedata.normalize("NFC", text)
    if sum(1 for ch in text if not ch.isspace()) != len(native_chars):
        return text
    native = iter(native_chars)
    return "".join(ch if ch.isspace() else next(native) for ch in text)


def _only_marker_before(docling_chars: str, native_chars: str) -> bool:
    prefix = native_chars[: len(native_chars) - len(docling_chars)]
    return native_chars.endswith(docling_chars) and bool(_LIST_MARKER_RE.fullmatch(prefix))


def restore_marker(marker: str, native_text: str) -> str:
    """Docling 이 바꿔 적은 목록 기호("·")를 원본 글자 층의 기호("•")로 되돌린다."""
    lead = native_text.lstrip()[: len(marker)]
    return lead if lead != marker and _as_docling_writes(lead) == marker else marker


def choose_spacing(docling_text: str, native_text: str) -> str:
    """두 글의 글자가 같으면(원본 앞의 목록 번호는 허용) 띄어쓰기가 덜 깨진 쪽을 돌려준다. 원본 글은 한 문단으로 잇는다.
    한글은 같은데 Docling 이 숫자·기호를 옮기거나 빠뜨렸으면 원본 글을 쓴다. Docling 글을 쓸 때도 Docling 이
    바꿔 적은 글자("·", 곧은 따옴표)는 원본 글자로 되돌린다."""
    native_flat = " ".join(native_text.split())
    docling_chars, native_chars = _compact(docling_text), _compact(native_flat)
    if not docling_chars or not native_chars:
        return docling_text
    if _has_phantom_symbols(docling_text, native_flat):
        return native_flat
    native_view = _docling_view(docling_chars, native_chars)
    if native_view != docling_chars and _restores_symbols(docling_chars, native_view):
        if not _only_marker_before(docling_chars, native_view):
            return native_flat
    if native_view != docling_chars and not _only_marker_before(docling_chars, native_view):
        return docling_text
    if spacing_score(native_flat) < spacing_score(docling_text):
        return native_flat
    return _with_native_chars(docling_text, native_chars[len(native_chars) - len(docling_chars):])


def _page_chars(page, counts: dict | None = None) -> list[dict]:
    """PyMuPDF 쪽의 글자를 pdfplumber 글자 모양(x0, x1, top, bottom, text, upright)으로 바꾼다.
    counts 를 주면 읽은 글자 수("chars")와 겹쳐 그려 뺀 글자 수("duplicates")를 적는다.

    글자 높이는 pdfplumber 처럼 기준선에서 글꼴 크기로 잡는다. 글 조립(공백, 줄 나눔)은 pdfplumber 의
    extract_text 에 맡겨 원본 글자 층 읽기 결과를 그대로 유지한다."""
    chars: list[dict] = []
    seen: set[tuple] = set()
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            upright = abs(line["dir"][1]) < 1e-3 and line["dir"][0] > 0
            for span in line["spans"]:
                size = span["size"]
                for ch in span["chars"]:
                    # 같은 자리에 같은 글자를 두 번 그린 PDF 는 한 번만 센다. 한글에서 내보낸 휴직규정은 한 겹에 한글만,
                    # 다른 겹에 숫자와 괄호까지 그려 원본 글이 "제제1조조((목목적적))"가 되었고, 그래서 Docling 이
                    # 숫자를 옮긴 "제 조 목적 1 ( )"를 원본 글로 바로잡지 못했다(2026-11-27)
                    key = (ch["c"], _rounded(ch["bbox"][0]), _rounded(ch["origin"][1]))
                    if key in seen:
                        if counts is not None:
                            counts["duplicates"] = counts.get("duplicates", 0) + 1
                        continue
                    seen.add(key)
                    if counts is not None:
                        counts["chars"] = counts.get("chars", 0) + 1
                    top = ch["origin"][1] - size * _ASCENT_RATIO
                    chars.append({
                        "x0": ch["bbox"][0], "x1": ch["bbox"][2], "top": top, "bottom": top + size,
                        "doctop": top, "text": ch["c"], "upright": upright, "size": size, "font": span["font"],
                    })
    return chars


def page_symbol_chars(
    spans: Iterable[tuple[str, str]], real_font_name: Callable[[str], str | None],
) -> dict[str, str]:
    """쪽의 (글꼴 이름, 글) 묶음에서 기호 글꼴 코드(U+F020~F0FF) → 화면 글자. 글꼴 이름이 가려진 내장 글꼴
    ("CIDFont+F4")은 real_font_name 으로 실제 이름("Wingdings Regular")을 본다. 같은 코드가 표를 모르는 글꼴
    (아이콘 Type3, 수식 글꼴)에도 쓰였으면 어느 글자인지 모르므로 넣지 않는다."""
    shown: dict[str, str | None] = {}
    for font, text in spans:
        for char in text:
            if not is_symbol_code(char):
                continue
            kind = symbol_font_kind(font) or symbol_font_kind(real_font_name(font))
            glyph = symbol_char(char, kind)
            shown[char] = glyph if shown.get(char, glyph) == glyph else None
    return {code: glyph for code, glyph in shown.items() if glyph}


def real_font_namer(doc, page, cache: dict[int, str | None]) -> Callable[[str], str | None]:
    """글자 층의 글꼴 이름 → 내장 글꼴 파일 안의 실제 이름. "CIDFont+F4" 처럼 이름을 가린 글꼴을 알아보려고 쓴다.
    cache 는 글꼴 xref → 이름이며 같은 문서를 읽는 동안 이어 쓴다."""
    import fitz  # pymupdf

    xrefs = {font[3]: font[0] for font in page.get_fonts(full=True)}

    def real_name(font: str) -> str | None:
        xref = xrefs.get(font)
        if not xref:
            return None
        if xref not in cache:
            try:
                cache[xref] = fitz.Font(fontbuffer=doc.extract_font(xref)[3]).name
            except Exception:  # 글꼴 파일을 못 읽으면 이름을 모르는 글꼴로 둔다
                cache[xref] = None
        return cache[xref]

    return real_name


def with_page_symbols(doc, page, text: str, cache: dict[int, str | None] | None = None) -> str:
    """PyMuPDF 쪽에서 읽은 text 의 기호 글꼴 코드를 그 쪽에서 그려진 글꼴의 화면 글자로 바꾼 새 글.
    그림 영역 안 글처럼 NativeRegionReader 를 거치지 않는 글에 쓴다. 예전에는 그림으로 잡힌 쪽의 "●" 가
    청크에서 빈칸으로 남았다(법령심사 PDF, 세원화성 보고서 [그림 13], 2026-11-26)."""
    if not text or not any(is_symbol_code(ch) for ch in text):
        return text
    symbols = page_symbol_map(doc, page, cache)
    return "".join(symbols.get(ch, ch) for ch in text)


def page_symbol_map(doc, page, cache: dict[int, str | None] | None = None) -> dict[str, str]:
    """PyMuPDF 쪽의 기호 글꼴 코드 → 화면 글자(page_symbol_chars). 한 쪽의 글 여러 개(본문, 표 칸)를 바꿀 때 한 번만 센다."""
    spans = [(c["font"], c["text"]) for c in _page_chars(page) if is_symbol_code(c["text"])]
    if not spans:
        return {}
    return page_symbol_chars(spans, real_font_namer(doc, page, {} if cache is None else cache))


class PdfSymbolPages:
    """PDF 쪽마다 기호 글꼴 코드 → 화면 글자. Docling 을 거치지 않는 PDF 읽기(pdf_adapter, pdfplumber)가 쓴다.
    예전에는 이 경로에 바꾸는 단계가 없어 법령심사 PDF 의 "●" 가 파싱 본문에 사설 영역 코드로 남았다(2026-11-26).
    처음 쓸 때 한 번만 열고, 열거나 읽지 못하면 빈 표를 돌려준다(기호 글자 보강일 뿐이다)."""

    def __init__(self, file_path: Path, warnings: list[str]) -> None:
        self._path = file_path
        self._warnings = warnings
        self._doc = None
        self._failed = False
        self._fonts: dict[int, str | None] = {}

    def for_page(self, page_no: int) -> dict[str, str]:
        if self._failed:
            return {}
        try:
            if self._doc is None:
                import fitz  # pymupdf

                self._doc = fitz.open(str(self._path))
            if page_no < 1 or page_no > self._doc.page_count:
                return {}
            return page_symbol_map(self._doc, self._doc[page_no - 1], self._fonts)
        except Exception as exc:  # 기호 글자 보강일 뿐이다. 실패하면 글을 그대로 쓴다
            self._failed = True
            self._warnings.append(f"기호 글꼴 글자 읽기 실패: {exc}")
            return {}

    def close(self) -> None:
        if self._doc is not None:
            self._doc.close()
            self._doc = None


def with_symbol_map(text: str, symbols: dict[str, str]) -> str:
    """text 의 기호 글꼴 코드를 symbols(page_symbol_map)로 바꾼 새 글."""
    if not symbols or not text:
        return text
    return "".join(symbols.get(ch, ch) for ch in text)


class NativeRegionReader:
    """원본 PDF 글자 층에서 Docling 요소 영역의 글을 읽는다. 처음 쓸 때 한 번만 열고, 열지 못하면 ""만 돌려준다.
    쪽 글자 정보는 지금 읽는 쪽 하나만 들고 있다(수백 쪽 문서에서 메모리가 쌓이지 않게).

    글자 위치는 PyMuPDF 로 읽는다. 처음에는 pdfplumber 의 within_bbox 를 요소마다 불렀는데, pdfplumber 가 쪽을
    해석하는 비용 때문에 기계설비 매뉴얼(글 요소 6천여 개)의 텍스트 추출이 430초에서 시간 제한 1800초를 넘겼다
    (2026-11-20). 다섯 문서 표본에서 대조 결과는 같고 읽기 시간은 3~60배 줄었다."""

    def __init__(self, file_path: Path, warnings: list[str]) -> None:
        self._path = file_path
        self._warnings = warnings
        self._doc = None
        self._failed = False
        self._page_no: int | None = None
        self._chars: list[dict] = []
        self._size: tuple[float, float] = (0.0, 0.0)
        self._symbols: dict[str, str] = {}
        self._font_names: dict[int, str | None] = {}
        self._duplicate_share = 0.0

    def has_duplicate_layer(self, page_no: int) -> bool:
        """이 쪽이 같은 글을 두 겹으로 그린 쪽인가(겹쳐 그린 글자가 DUPLICATE_LAYER_SHARE 넘게 섞임)."""
        if self._failed:
            return False
        try:
            if self._chars_for(page_no) is None:
                return False
        except Exception:  # noqa: BLE001 - 판정 보조일 뿐이다. 읽지 못하면 겹친 쪽이 아닌 것으로 본다
            return False
        return self._duplicate_share > DUPLICATE_LAYER_SHARE

    def _chars_for(self, page_no: int) -> list[dict] | None:
        if self._doc is None:
            import fitz  # pymupdf

            self._doc = fitz.open(str(self._path))
        if page_no < 1 or page_no > self._doc.page_count:
            return None
        if self._page_no != page_no:
            page = self._doc[page_no - 1]
            counts: dict = {}
            self._chars, self._size, self._page_no = _page_chars(page, counts), (page.rect.width, page.rect.height), page_no
            read = counts.get("chars", 0) + counts.get("duplicates", 0)
            self._duplicate_share = counts.get("duplicates", 0) / read if read else 0.0
            symbol_spans = [(c["font"], c["text"]) for c in self._chars if is_symbol_code(c["text"])]
            self._symbols = page_symbol_chars(symbol_spans, self._font_namer(page)) if symbol_spans else {}
        return self._chars

    def _font_namer(self, page) -> Callable[[str], str | None]:
        return real_font_namer(self._doc, page, self._font_names)

    def with_symbols(self, page_no: int, text: str) -> str:
        """text 의 기호 글꼴 코드를 그 쪽에서 그려진 글꼴의 화면 글자로 바꾼 새 글(page_symbol_chars).
        예전에는 "\\uf06c 법제처의 업무" 의 "●" 가 파싱 본문과 청크에서 빈칸으로 보였다(법령심사 PDF, 2026-11-26)."""
        if self._failed or not text or not any(is_symbol_code(ch) for ch in text):
            return text
        try:
            if self._chars_for(page_no) is None:
                return text
        except Exception as exc:  # 기호 글자 보강일 뿐이다. 실패하면 글을 그대로 쓴다
            self._failed = True
            self._warnings.append(f"기호 글꼴 글자 읽기 실패: {exc}")
            return text
        return "".join(self._symbols.get(ch, ch) for ch in text)

    def read(self, page_no: int, bbox: tuple[float, float, float, float] | None) -> str:
        if bbox is None or self._failed:
            return ""
        try:
            chars = self._chars_for(page_no)
            if chars is None:
                return ""
            from pdfplumber.utils import extract_text

            width, height = self._size
            left, right = sorted((bbox[0], bbox[2]))
            top, bottom = bbox[1], bbox[3]
            if top > bottom:  # 왼쪽 아래 원점(Docling) → 왼쪽 위 원점
                top, bottom = height - top, height - bottom
            x0, x1 = max(0.0, left - _REGION_PAD), min(width, right + _REGION_PAD)
            y0, y1 = max(0.0, top - _REGION_PAD), min(height, bottom + _REGION_PAD)
            if x1 <= x0 or y1 <= y0:
                return ""
            # 글자 중심이 영역 안이면 담는다. 예전에는 글자 전체가 들어와야 해서, Docling 영역이 글자 윗변보다 4pt 아래에서
            # 시작한 문단은 원본 글이 통째로 비었다(임금피크제시행내규 요소 40개 중 28개, PDF 26건 요소 31,686개 중 653개 →
            # 497개, 2026-11-27 실측)
            inside = [
                c for c in chars
                if x0 <= (c["x0"] + c["x1"]) / 2 <= x1 and y0 <= (c["top"] + c["bottom"]) / 2 <= y1
            ]
            return (extract_text(inside) or "") if inside else ""
        except Exception as exc:  # 띄어쓰기 보강일 뿐이다. 실패하면 Docling 글을 그대로 쓴다
            self._failed = True
            self._warnings.append(f"본문 영역 원본 텍스트 읽기 실패: {exc}")
            return ""

    def close(self) -> None:
        self._chars, self._page_no = [], None
        if self._doc is not None:
            self._doc.close()
