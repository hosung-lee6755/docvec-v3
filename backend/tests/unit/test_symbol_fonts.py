"""기호 글꼴(Wingdings, Symbol) 글자를 화면에 보이는 유니코드 글자로 적는다(2026-11-26).

문서는 기호 글꼴 글자를 사용자 영역 코드(U+F020~F0FF, 글꼴 코드 + 0xF000)로 저장한다. 그대로 두면 파싱 본문과
RAG 청크에서 빈칸으로 보였다(제안요청서 HWP "❑ 사업명", 공고 HWPX "❶ SMTECH 접속", 법령심사 PDF "●")."""
from app.pipeline.adapters.symbol_fonts import symbol_char, symbol_font_kind, with_symbol_font_chars


def test_font_names_are_recognised_by_family():
    assert symbol_font_kind("Wingdings") == "wingdings"
    assert symbol_font_kind("Wingdings Regular") == "wingdings"
    assert symbol_font_kind("ABCDEF+Wingdings-Regular") == "wingdings"
    assert symbol_font_kind("Symbol") == "symbol"
    assert symbol_font_kind("SymbolMT") == "symbol"
    # 표를 모르는 기호 글꼴과 보통 글꼴은 기호 글꼴로 보지 않는다
    assert symbol_font_kind("Wingdings 2") is None
    assert symbol_font_kind("Webdings") is None
    assert symbol_font_kind("OpenSymbol") is None
    assert symbol_font_kind("맑은 고딕") is None


def test_wingdings_codes_seen_in_uploaded_documents():
    # 원본 PDF 에 그려진 모양과 문서 안 쓰임새(글머리, 번호 단계)로 확인한 글자
    assert symbol_char("", "wingdings") == "●"
    assert symbol_char("", "wingdings") == "❍"
    assert symbol_char("", "wingdings") == "❑"
    assert symbol_char("", "wingdings") == "•"
    assert symbol_char("", "wingdings") == "✓"
    assert [symbol_char(chr(code), "wingdings") for code in range(0xF08C, 0xF092)] == list("❶❷❸❹❺❻")


def test_symbol_font_codes_are_greek_and_math():
    assert symbol_char("", "symbol") == "μ"
    assert symbol_char("", "symbol") == "≥"
    # 기호 글꼴 코드를 바로 적은 글(0x20~0xFF)도 같은 표로 읽는다(슬라이드 글머리표 char="ü")
    assert symbol_char("ü", "wingdings") == "✓"


def test_codes_without_a_known_character_are_left_alone():
    assert symbol_char("", "wingdings") is None   # 기호 글꼴 코드 범위(0x20~0xFF) 밖이다
    assert symbol_char("", "wingdings") is None   # 다른 사용자 영역 글자는 글꼴만의 글자다
    assert symbol_char("가", "wingdings") is None


def test_text_keeps_everything_but_the_symbol_codes():
    text = " 사업명 : 「지능형」\n  세부  그대로"

    assert with_symbol_font_chars(text, "wingdings") == "❑ 사업명 : 「지능형」\n ❍ 세부  그대로"
    # 보통 글자(라틴 글자 포함)는 바꾸지 않는다. 기호 글꼴 코드는 사용자 영역 글자만 바꾼다
    assert with_symbol_font_chars("quality ", "wingdings") == "quality ✓"
    assert with_symbol_font_chars("", None) == ""
