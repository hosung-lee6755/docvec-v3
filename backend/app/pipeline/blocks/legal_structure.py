"""법령·규정 문서의 조문 구조(2026-11-27, 문서유형별_처리_방안_검토 4.2).

규정은 제목 단계가 글꼴이 아니라 번호 체계로 정해진다. 편 > 장 > 절 > 관 > 조이고, 부칙과 별표·별지는 본칙과 같은
최상위다. 예전 구조 분석은 "제N장"과 "제N조"를 모두 1단계 제목으로 보거나(정규식 경로) 글꼴 크기로 단계를 짐작해
(Docling 경로) 제3장이 제2장 아래로, 부칙이 마지막 장 아래로 들어갔고, 조는 "제1조(목적) 이 규정은 …"처럼 본문과 한
줄로 붙어 section_path 에 들어가지 않았다.

이 모듈은 구조 분석이 만든 블록 목록을 받아, 조문 단위 줄을 번호 체계의 단계를 가진 제목으로 바꾸고, 조 제목과 본문이
한 줄이면 제목("제1조(목적)")과 본문을 나눈다. 항(①②), 호(1. 2.), 목(가. 나.)은 조 본문으로 둔다. 조 하나가 청크
하나가 되도록 청크 분할은 조 제목마다 끊는다(storage_blocks).
"""
import re

# (순위, 정규식). 순위가 작을수록 위 단계다. 부칙과 별표는 본칙의 편과 같은 최상위로 둔다
_UNITS: list[tuple[int, re.Pattern]] = [
    (0, re.compile(r"^\s*부\s*칙(?=\s*$|\s*[<(〈［\[]|\s+\S)")),
    (0, re.compile(r"^\s*[\[【<〈(]?\s*별\s*[표지]\s*\d*")),
    (1, re.compile(r"^\s*제\s*\d+\s*편(?!\S*[을를이가은는])")),
    (2, re.compile(r"^\s*제\s*\d+\s*장(?!\S*[을를이가은는])")),
    (3, re.compile(r"^\s*제\s*\d+\s*절(?!\S*[을를이가은는])")),
    (4, re.compile(r"^\s*제\s*\d+\s*관(?!\S*[을를이가은는])")),
]
# 조 제목: "제1조(목적)", "제7조의2(난임휴직)", "제12조 (선거관리위원회 구성)". 괄호 제목이 없는 "제3조 삭제" 도 조다
_ARTICLE_RE = re.compile(r"^\s*(제\s*\d+\s*조(?:\s*의\s*\d+)?)\s*(\([^()]{1,40}\))?")
_ARTICLE_RANK = 5
# 다른 조문을 가리키는 본문 문장("제5조에 따른 …")은 조 제목이 아니다
_REFERENCE_TAIL_RE = re.compile(r"^\s*(?:제\s*\d+\s*항|[에의을를은는이가와과도로]|및|또는|부터|까지|에서)")
# 단위 줄(장·절 등)로 볼 최대 길이. 더 길면 본문 문장이다
_MAX_HEADING_CHARS = 60

Block = tuple  # (node_type, level, span_start, span_end, text, layout)


def article_heading(text: str) -> str | None:
    """줄 앞의 조 제목("제1조(목적)"). 조 제목으로 시작하지 않거나 다른 조문을 가리키는 문장이면 None."""
    match = _ARTICLE_RE.match(text or "")
    if not match:
        return None
    rest = text[match.end():]
    if not match.group(2) and _REFERENCE_TAIL_RE.match(rest):
        return None
    return text[: match.end()].strip()


def unit_rank(text: str) -> int | None:
    """조문 단위의 순위(부칙·별표 0, 편 1, 장 2, 절 3, 관 4, 조 5). 단위 줄이 아니면 None."""
    stripped = (text or "").strip()
    if article_heading(stripped):
        return _ARTICLE_RANK
    for rank, pattern in _UNITS:
        if pattern.match(stripped) and len(stripped) <= _MAX_HEADING_CHARS:
            return rank
    return None


# 자동 판별 기준(2026-11-27 전체 문서 실측). 규정 28건은 모두 제1조로 시작했고 조 하나당 본문이 674자 이하였다.
# 조문을 인용하거나 계약 조항을 덧붙인 문서(기계설비 기술기준 매뉴얼, 제안요청서)는 조당 5천 자가 넘었고 매뉴얼은
# 제9조부터 시작했다
AUTO_MIN_ARTICLES = 5
AUTO_MAX_CHARS_PER_ARTICLE = 1500


def _article_numbers(texts: list[str]) -> list[int]:
    numbers = []
    for text in texts:
        heading = article_heading((text or "").strip())
        if heading:
            numbers.append(int(re.search(r"\d+", heading).group()))
    return numbers


def looks_like_regulation(texts: list[str], min_articles: int = AUTO_MIN_ARTICLES) -> bool:
    """자동 판별. 서로 다른 조가 min_articles 개 이상이고, 제1조로 시작하며, 조 하나당 글이 짧으면 규정으로 본다.

    사용자가 유형을 지정하지 않은 문서에만 쓴다. 보고서나 매뉴얼이 조문 몇 개를 인용했다고 규정으로 바꾸면 그 문서의
    제목 구조가 무너지므로, 문서 대부분이 조문일 때만 규정으로 본다."""
    numbers = _article_numbers(texts)
    if len(set(numbers)) < min_articles or numbers[0] != 1:
        return False
    total_chars = sum(len(text or "") for text in texts)
    return total_chars / len(numbers) <= AUTO_MAX_CHARS_PER_ARTICLE


def _levels(ranks: list[int]) -> dict[int, int]:
    """문서에 실제로 나온 순위만 1부터 차례로 단계를 준다(장이 없는 규정은 조가 1단계)."""
    return {rank: index + 1 for index, rank in enumerate(sorted(set(ranks)))}


def _split_article(block: Block, heading: str) -> list[Block]:
    """조 제목과 본문이 한 블록이면 제목 블록과 본문 블록으로 나눈다. 위치는 원문 위치를 그대로 따른다."""
    _node_type, _level, start, end, text, layout = block
    head_end = text.find(heading) + len(heading)
    body = text[head_end:]
    stripped_body = body.lstrip()
    if not stripped_body:
        return [block]
    body_offset = head_end + (len(body) - len(stripped_body))
    split = None if start is None else start + head_end
    body_start = None if start is None else start + body_offset
    heading_block = ("HEADING", None, start, split, text[:head_end].strip(), layout)
    body_block = ("PARAGRAPH", None, body_start, end, stripped_body, layout)
    return [heading_block, body_block]


_KEEP_TYPES = ("TOC", "TABLE", "HEADER", "FOOTER", "FOOTNOTE", "CAPTION")


def apply_legal_structure(blocks: list[Block]) -> list[Block]:
    """조문 단위 줄을 번호 체계 단계의 제목으로 바꾸고 조 제목과 본문을 나눈 새 블록 목록.

    목차(TOC)와 표는 건드리지 않는다. 단위가 아닌 제목(글꼴로만 잡힌 줄 등)은 문단으로 내린다. 규정에서 그런 줄은
    대개 개정 이력이나 조 안의 강조 문구이고, 제목으로 두면 조 위의 단계를 흐트러뜨린다. 첫 단위보다 앞에 있는 첫
    제목(규정 이름)만 1단계 제목으로 남긴다. 첫 장이나 조가 나오면 그 제목은 단계 스택에서 빠진다."""
    ranks = [None if block[0] in _KEEP_TYPES else unit_rank(block[4]) for block in blocks]
    levels = _levels([rank for rank in ranks if rank is not None])
    if _ARTICLE_RANK not in levels:
        return list(blocks)  # 조가 없으면 규정 구조로 다루지 않는다
    first_unit = next(index for index, rank in enumerate(ranks) if rank is not None)
    title_index = next(
        (index for index, block in enumerate(blocks[:first_unit]) if block[0] == "HEADING"), None,
    )
    result: list[Block] = []
    for index, (block, rank) in enumerate(zip(blocks, ranks, strict=False)):
        node_type, _level, start, end, text, layout = block
        if node_type in _KEEP_TYPES:
            result.append(block)
        elif index == title_index:
            result.append(("HEADING", 1, start, end, text, layout))
        elif rank is None:
            result.append(("PARAGRAPH", None, start, end, text, layout) if node_type == "HEADING" else block)
        elif rank == _ARTICLE_RANK:
            parts = _split_article(block, article_heading(text.strip()))
            head = parts[0]
            result.append(("HEADING", levels[rank], head[2], head[3], head[4], head[5]))
            result.extend(parts[1:])
        else:
            result.append(("HEADING", levels[rank], start, end, text, layout))
    return result
