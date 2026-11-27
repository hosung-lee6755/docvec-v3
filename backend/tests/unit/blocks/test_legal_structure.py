"""규정 조문 구조(2026-11-27, 휴직규정 등 규정집의 조 단위 section_path·청크)."""
from app.pipeline.blocks.legal_structure import (
    apply_legal_structure,
    article_heading,
    looks_like_regulation,
    unit_rank,
)


def _block(node_type: str, text: str, start: int | None = 0, level: int | None = None):
    end = None if start is None else start + len(text)
    return (node_type, level, start, end, text, None)


def test_article_heading_reads_title_with_parenthesis_and_branch_number():
    assert article_heading("제1조(목적) 이 규정은 휴직에 관한 사항을 정한다.") == "제1조(목적)"
    assert article_heading("제7조의2(난임휴직) ① 직원은") == "제7조의2(난임휴직)"
    assert article_heading("제 12 조 (위원회) 위원회를 둔다") == "제 12 조 (위원회)"
    assert article_heading("제3조 삭제") == "제3조"


def test_a_sentence_referring_to_another_article_is_not_a_heading():
    assert article_heading("제5조에 따른 휴직 기간은 경력에 넣는다.") is None
    assert article_heading("제5조제2항의 경우에는") is None
    assert article_heading("제5조 및 제6조를 준용한다.") is None


def test_unit_rank_orders_chapter_section_and_article():
    assert unit_rank("제1편 총칙") == 1
    assert unit_rank("제2장 휴직") == 2
    assert unit_rank("제1절 통칙") == 3
    assert unit_rank("제1관 일반") == 4
    assert unit_rank("제4조(휴직의 종류)") == 5
    assert unit_rank("부 칙") == 0
    assert unit_rank("부칙 <2026. 10. 29.>") == 0
    assert unit_rank("[별표 1] 휴직 기간") == 0
    assert unit_rank("이 규정은 공포한 날부터 시행한다.") is None
    # 장 번호로 시작해도 문장이면 단위가 아니다
    assert unit_rank("제2장을 준용한다.") is None


def test_looks_like_regulation_needs_several_distinct_articles_starting_at_one():
    articles = [f"제{n}조(항목{n}) 본문" for n in range(1, 6)]
    assert looks_like_regulation(articles)
    assert looks_like_regulation(articles[:3], min_articles=3)
    assert not looks_like_regulation(articles[:4])
    assert not looks_like_regulation(["제1조(목적) …", "제1조(목적) …", "보고서 본문"])
    assert not looks_like_regulation(["제5조에 따른 기준", "1. 개요"])


def test_documents_quoting_a_few_articles_are_not_regulations():
    # 기계설비 기술기준 매뉴얼은 제9조부터 인용했고, 제안요청서는 긴 본문 뒤에 계약 조항을 붙였다(2026-11-27 실측)
    quoted = [f"제{n}조(기준{n}) 내용" for n in range(9, 20)]
    assert not looks_like_regulation(quoted)
    appended = ["사업 개요 " * 5000] + [f"제{n}조(조항{n}) 내용" for n in range(1, 16)]
    assert not looks_like_regulation(appended)


def test_article_line_is_split_into_heading_and_body_with_original_offsets():
    text = "제1조(목적) 이 규정은 휴직에 관한 사항을 정한다."
    blocks = [
        ("HEADING", 1, 0, 4, "휴직규정", None),
        _block("PARAGRAPH", text, 10),
        _block("PARAGRAPH", "제2조(정의) 정의는 다음과 같다.", 50),
        _block("PARAGRAPH", "제3조(적용) 모든 직원에게 적용한다.", 80),
    ]

    result = apply_legal_structure(blocks)

    assert result[0] == ("HEADING", 1, 0, 4, "휴직규정", None)  # 첫 조 앞의 규정 이름은 제목으로 남는다
    heading, body = result[1], result[2]
    assert heading[0] == "HEADING" and heading[4] == "제1조(목적)"
    assert (heading[2], heading[3]) == (10, 10 + len("제1조(목적)"))
    assert body[0] == "PARAGRAPH" and body[4] == "이 규정은 휴직에 관한 사항을 정한다."
    assert body[2] == 10 + len("제1조(목적) ") and body[3] == 10 + len(text)


def test_levels_follow_the_numbering_hierarchy_not_the_font():
    # 글꼴로는 모두 1단계였던 장·조·부칙이 편장절조 순서대로 단계를 받는다
    blocks = [
        ("HEADING", 1, 0, 6, "제1장 총칙", None),
        ("HEADING", 1, 10, 17, "제1조(목적)", None),
        ("HEADING", 1, 20, 27, "제2장 휴직", None),
        ("HEADING", 1, 30, 37, "제2조(종류)", None),
        ("HEADING", 3, 40, 43, "부 칙", None),
        ("PARAGRAPH", None, 50, 60, "제1조(시행) 이 규정은 공포한 날부터 시행한다.", None),
    ]

    levels = {b[4]: b[1] for b in apply_legal_structure(blocks) if b[0] == "HEADING"}

    assert levels["부 칙"] == 1
    assert levels["제1장 총칙"] == 2 and levels["제2장 휴직"] == 2
    assert levels["제1조(목적)"] == 3 and levels["제2조(종류)"] == 3
    assert levels["제1조(시행)"] == 3


def test_regulation_without_chapters_puts_articles_at_level_one():
    blocks = [_block("PARAGRAPH", f"제{n}조(항목{n}) 본문 {n}", n * 20) for n in range(1, 4)]

    result = apply_legal_structure(blocks)

    assert [b[1] for b in result if b[0] == "HEADING"] == [1, 1, 1]


def test_non_unit_headings_become_paragraphs_and_tables_are_kept():
    blocks = [
        ("HEADING", 1, 0, 4, "휴직규정", None),
        ("TABLE", None, 10, 20, "[표 1]", None),
        ("TOC", None, 20, 30, "제1조(목적) ····· 1", None),
        _block("PARAGRAPH", "제1조(목적) 본문", 40),
        ("HEADING", 2, 50, 58, "개정 이력 안내", None),
        _block("PARAGRAPH", "제2조(정의) 본문", 60),
        _block("PARAGRAPH", "제3조(적용) 본문", 80),
    ]

    result = apply_legal_structure(blocks)

    assert result[1][0] == "TABLE" and result[2][0] == "TOC"
    assert result[5][0] == "PARAGRAPH" and result[5][4] == "개정 이력 안내"


def test_document_without_articles_is_returned_unchanged():
    blocks = [("HEADING", 1, 0, 5, "1. 개요", None), _block("PARAGRAPH", "제2장 본문", 10)]

    assert apply_legal_structure(blocks) == blocks


def test_article_heading_without_body_stays_one_block():
    blocks = [_block("PARAGRAPH", f"제{n}조(항목{n})", n * 20) for n in range(1, 4)]

    result = apply_legal_structure(blocks)

    assert len(result) == 3 and all(b[0] == "HEADING" for b in result)
