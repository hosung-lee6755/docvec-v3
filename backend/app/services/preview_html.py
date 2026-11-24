"""올린 HTML을 원본 모양 그대로 PDF로 그리기 전에 안전하게 다듬는다(2026-11-23).

예전 HTML 미리보기는 추출한 글과 표만 다시 적어 원본 모양과 달랐다. 이제 원본 HTML을 LibreOffice로
그리는데, LibreOffice는 <img src="http://…">, <link href>, CSS의 url(…)을 서버에서 불러온다. 그러면
올린 사람이 서버로 하여금 외부나 내부 주소로 요청을 보내게 할 수 있다(SSRF).

그래서 지울 것을 고르지 않고 남길 것만 고른다(허용 목록).

- 태그는 글과 표를 그리는 태그만 남긴다. 목록에 없는 태그는 태그만 버리고 안의 글은 남긴다. 스크립트, 프레임,
  개체, SVG, MathML처럼 다른 자원을 끌어오는 태그는 안의 내용까지 버린다.
- 이름이 영문자, 숫자, 하이픈이 아닌 태그와 속성은 버린다. HTMLParser는 `=src`나 `"src` 같은 이름도 받아
  주는데, 이름을 그대로 다시 적으면 LibreOffice가 다르게 읽을 수 있다.
- 속성은 모양에 필요한 것만 남긴다. src는 내장 래스터 이미지(data:image/png 등, base64)만 남긴다.
  data: 안의 SVG는 다시 외부 주소를 부를 수 있어 뺀다.
- style은 url, image-set, 역슬래시 이스케이프, 주석처럼 주소를 숨길 수 있는 글이 있으면 통째로 버린다.
- DOCTYPE 같은 선언, 주석, 처리 지시는 버린다(외부 DTD를 부를 수 있다).
"""
import html
import re
from html.parser import HTMLParser

_DROP_WITH_CONTENT = frozenset({
    "script", "iframe", "frame", "frameset", "object", "embed", "applet", "noembed", "template",
    "svg", "math", "audio", "video", "canvas", "noframes", "xml",
})
_ALLOWED_TAGS = frozenset({
    "html", "head", "body", "title", "style",
    "div", "span", "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "main", "nav", "aside", "address", "center",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup", "col",
    "ul", "ol", "li", "dl", "dt", "dd",
    "b", "strong", "i", "em", "u", "s", "strike", "del", "ins", "sub", "sup", "small", "big", "font",
    "mark", "abbr", "q", "cite", "code", "pre", "kbd", "samp", "var", "blockquote", "time", "label",
    "a", "img", "figure", "figcaption",
})
_ALLOWED_ATTRIBUTES = frozenset({
    "style", "class", "id", "title", "lang", "dir",
    "width", "height", "colspan", "rowspan", "span", "align", "valign",
    "border", "cellpadding", "cellspacing", "bgcolor", "color", "face", "size",
    "alt", "start", "type", "src",
})
_VOID_TAGS = frozenset({"area", "br", "col", "hr", "img", "input", "wbr"})

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_INLINE_IMAGE_RE = re.compile(r"^data:image/(png|jpeg|jpg|gif|webp|bmp);base64,[a-z0-9+/=\s]*$", re.IGNORECASE)
# 이 글이 들어 있는 CSS는 주소를 부르거나 숨길 수 있다. 이스케이프(\75 rl)나 주석(u/**/rl)으로 돌려 쓴 것도 막는다
_CSS_UNSAFE_RE = re.compile(r"url|image-set|image\(|src\s*\(|@import|@font-face|expression|behavior|binding|\\|/\*", re.IGNORECASE)


def _is_inline_image(value: str) -> bool:
    return bool(_INLINE_IMAGE_RE.match(value.strip()))


def sanitize_css(css: str) -> str:
    """선언(;로 나눈 조각)마다 보고 주소를 부를 수 있는 선언만 버린다. 글자 색, 테두리, 여백 같은 모양은 남는다.
    조각 하나라도 url, 역슬래시, 주석을 품으면 버리므로 ;를 끼워 나눠도 남는 조각에서 주소가 되살아나지 않는다."""
    declarations = [d for d in css.split(";") if d.strip() and not _CSS_UNSAFE_RE.search(d)]
    return ";".join(declarations)


def _sanitize_style_sheet(css: str) -> str:
    """<style> 안의 규칙을 하나씩 보고, 주소를 부를 수 있는 규칙만 버린다. @media 같은 겹친 블록은 안쪽 규칙만 남는다."""
    rules = re.findall(r"[^{}]*\{[^{}]*\}", css)
    return "".join(rule for rule in rules if not _CSS_UNSAFE_RE.search(rule))


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skipping: list[str] = []
        self._in_style = False

    def _attrs(self, attrs: list[tuple[str, str | None]]) -> str:
        kept = []
        for name, value in attrs:
            name = name.lower()
            if not _NAME_RE.match(name) or name not in _ALLOWED_ATTRIBUTES:
                continue
            value = value or ""
            if name == "src" and not _is_inline_image(value):
                continue
            if name == "style":
                value = sanitize_css(value)
                if not value:
                    continue
            kept.append(f' {name}="{html.escape(value, quote=True)}"')
        return "".join(kept)

    def _keeps(self, tag: str) -> bool:
        return bool(_NAME_RE.match(tag)) and tag in _ALLOWED_TAGS

    def handle_starttag(self, tag, attrs):
        if self._skipping or tag in _DROP_WITH_CONTENT:
            if tag in _DROP_WITH_CONTENT and tag not in _VOID_TAGS:
                self._skipping.append(tag)
            return
        if not self._keeps(tag):
            return
        self._in_style = tag == "style"
        self.out.append(f"<{tag}{self._attrs(attrs)}>")

    def handle_startendtag(self, tag, attrs):
        if self._skipping or not self._keeps(tag):
            return
        self.out.append(f"<{tag}{self._attrs(attrs)}>")

    def handle_endtag(self, tag):
        if self._skipping:
            if tag == self._skipping[-1]:
                self._skipping.pop()
            return
        if not self._keeps(tag) or tag in _VOID_TAGS:
            return
        if tag == "style":
            self._in_style = False
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if self._skipping:
            return
        if self._in_style:
            # <style> 안의 글은 HTML로 이스케이프하지 않으므로 태그를 닫는 글자가 섞이지 않게 한다
            self.out.append(_sanitize_style_sheet(data).replace("<", ""))
        else:
            self.out.append(html.escape(data, quote=False))

    # 선언(DOCTYPE), 주석, 처리 지시, CDATA는 버린다. 기본 동작도 버리지만, 외부 DTD를 부를 수 있어 명시해 둔다
    def handle_decl(self, decl):
        return

    def handle_comment(self, data):
        return

    def handle_pi(self, data):
        return

    def unknown_decl(self, data):
        return


def sanitize_html_for_render(source: str) -> str:
    parser = _Sanitizer()
    parser.feed(source)
    parser.close()
    # 원본의 meta를 지웠으므로 글자 인코딩을 다시 밝혀 둔다
    return '<meta charset="utf-8">' + "".join(parser.out)
