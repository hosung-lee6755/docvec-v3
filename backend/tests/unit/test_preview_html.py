"""올린 HTML을 원본 모양 그대로 PDF로 그리기 전에 스크립트와 외부 참조를 지운다(2026-11-23).

LibreOffice가 HTML을 열 때 <img src="http://…">나 <link href>를 서버에서 불러오면 서버가 외부·내부
주소로 요청을 보내게 된다(SSRF). 글, 표, 스타일, 내장 이미지(data:)는 원본 모양을 위해 남긴다."""
from app.services.preview_html import sanitize_html_for_render


def test_scripts_frames_and_external_resources_are_removed():
    source = (
        '<html><head><link rel="stylesheet" href="http://169.254.169.254/x.css">'
        "<script>alert(1)</script><base href=\"http://evil/\"></head>"
        '<body onload="steal()"><iframe src="http://internal/"></iframe>'
        '<img src="http://10.0.0.1/a.png" alt="그림"><p style="background:url(http://x/y.png);color:red">본문</p>'
        "</body></html>"
    )

    out = sanitize_html_for_render(source)

    for leaked in ("<script", "alert(1)", "<link", "<base", "<iframe", "onload", "169.254", "10.0.0.1", "http://x/"):
        assert leaked not in out
    assert "본문" in out and "color:red" in out and 'alt="그림"' in out


def test_tables_styles_and_inline_images_are_kept():
    source = (
        "<style>td{border:1px solid #000} .a{background:url('data:image/png;base64,AAAA')}</style>"
        '<table><tr><td colspan="2">합친 칸</td></tr></table>'
        '<img src="data:image/png;base64,iVBORw0KGgo=">'
        '<a href="https://example.com/page">링크 글자</a>'
    )

    out = sanitize_html_for_render(source)

    assert 'colspan="2"' in out and "합친 칸" in out
    assert "border:1px solid #000" in out
    # CSS의 url은 내장 이미지라도 버린다(이스케이프로 주소를 숨길 수 있어 url 자체를 받지 않는다)
    assert "url(" not in out
    assert 'src="data:image/png;base64,iVBORw0KGgo="' in out
    # 링크는 불러오지 않으므로 글자는 남기되 주소는 지운다
    assert "링크 글자" in out and "example.com" not in out


def test_css_imports_and_remote_fonts_in_style_blocks_are_removed():
    source = '<style>@import url("http://x/a.css"); @font-face{src:url(http://x/f.woff)} p{margin:0}</style><p>글</p>'

    out = sanitize_html_for_render(source)

    assert "http://x" not in out and "@import" not in out
    assert "p{margin:0}" in out and "<p>글</p>" in out


def test_text_is_escaped_when_written_back():
    out = sanitize_html_for_render("<p>a &lt; b &amp; c</p><p title='x\" onmouseover=\"y'>t</p>")

    assert "a &lt; b &amp; c" in out
    assert "onmouseover=\"" not in out


def test_mangled_tag_and_attribute_names_cannot_smuggle_a_source():
    # HTMLParser는 '=src', '"src' 같은 이름도 받아 준다. 그대로 다시 적으면 LibreOffice가 src로 읽을 수 있다
    for source in ('<img =src=http://169.254.169.254/x>', '<img "src=http://a/x>', '<a<img src=http://x/>t'):
        out = sanitize_html_for_render(source)
        assert "169.254" not in out and "http://a" not in out and "http://x" not in out


def test_urls_hidden_in_unclosed_escaped_or_commented_css_are_removed():
    for style in (
        "background:url(http://a/x",
        "background:ur\\6c(http://a/x)",
        "background:u/**/rl(http://a/x)",
        "background-image:image-set('http://a/x' 1x)",
    ):
        out = sanitize_html_for_render(f'<div style="{style};color:blue">t</div>')
        assert "http://a" not in out and "color:blue" in out


def test_doctype_with_external_dtd_and_unlisted_url_attributes_are_dropped():
    source = (
        '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0//EN" "http://internal/x.dtd">'
        '<img lowsrc=http://a dynsrc=http://b longdesc=http://c usemap=#m src="data:image/svg+xml,<svg/>">'
        '<svg><image href="http://d/"/></svg><p>글</p>'
    )

    out = sanitize_html_for_render(source)

    for leaked in ("DOCTYPE", "internal", "http://a", "http://b", "http://c", "usemap", "svg", "http://d"):
        assert leaked not in out
    assert "<p>글</p>" in out
