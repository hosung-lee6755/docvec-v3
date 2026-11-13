"""심층 검색의 질문 분해(v3 마일스톤 5).

복합 질문을 따로 검색할 수 있는 하위 질문 몇 개로 나눈다. 로컬 3B 모델은 형식을 자주 어기므로
JSON 배열, 번호 목록, 줄바꿈 목록을 모두 받아들이고, 해석하지 못하면 원 질문 하나로 되돌아간다.
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

MAX_SUBQUESTIONS = 3
_MIN_QUESTION_CHARS = 4
_MAX_QUESTION_CHARS = 300

DECOMPOSE_SYSTEM_PROMPT = (
    "너는 사내 문서 검색을 돕는 도우미다. 사용자의 질문을 문서 검색에 쓸 하위 질문으로 나눈다.\n"
    "- 질문이 여러 대상, 기간, 조건을 함께 묻거나 비교를 요구하면 각각을 따로 찾을 수 있는 하위 질문으로 나눈다.\n"
    f"- 하위 질문은 최대 {MAX_SUBQUESTIONS}개다. 하나만으로 충분하면 원래 질문 하나만 쓴다.\n"
    "- 각 하위 질문은 그것만 읽어도 무엇을 찾는지 알 수 있는 완결된 문장으로 쓴다.\n"
    '- 답은 JSON 문자열 배열 하나만 쓴다. 예: ["2027년 영업 목표는?", "2026년 영업 실적은?"]'
)

_LIST_MARKER = re.compile(r"^\s*(?:\d+\s*[.)]|[-*•·])\s*")
_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)

# 여러 대상, 조건, 비교를 함께 묻는다는 표시. 없으면 나누지 않는다.
# 3B 모델은 "연차 정보 알려줘" 같은 단순 질문도 "최근 5년 간의 연차 정보는?"처럼 묻지 않은 조건을
# 지어내 나눴고, 그 하위 질문에 엉뚱한 문서가 근거로 붙어 답이 어긋났다(2026-11-12).
_COMPOUND_MARKERS = re.compile(
    r"(?:와|과|랑|이랑|하고|및|그리고|또는|혹은)\s|비교|차이|각각|별로|대비|\bvs\b|[,/·]",
    re.IGNORECASE,
)
# 하위 질문이 사용자를 "당신"으로 부르면 문서가 아니라 모델에게 묻는 질문이 된다
_SECOND_PERSON = re.compile(r"당신|귀하|너의")
_NUMBER = re.compile(r"\d+")


def looks_compound(query: str) -> bool:
    """나눠 찾을 만한 복합 질문인지. 아니면 모델을 부르지 않고 원 질문으로 찾는다."""
    return bool(_COMPOUND_MARKERS.search(query)) or query.count("?") >= 2


def adds_unasked_detail(question: str, original: str) -> bool:
    """원 질문에 없던 숫자(연도, 기간)나 2인칭을 끌어들인 하위 질문인지."""
    asked_numbers = set(_NUMBER.findall(original))
    if any(n not in asked_numbers for n in _NUMBER.findall(question)):
        return True
    return bool(_SECOND_PERSON.search(question)) and not _SECOND_PERSON.search(original)


def decompose_messages(query: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": f"질문: {query}"}]


def _clean(item: str) -> str:
    item = _LIST_MARKER.sub("", item.strip())
    return item.strip().strip('"').strip("'").strip()


def _candidates(text: str) -> list[str]:
    match = _JSON_ARRAY.search(text or "")
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, list):
                return [str(x) for x in parsed if isinstance(x, (str, int, float))]
        except ValueError:
            pass
    return [line for line in (text or "").splitlines() if _LIST_MARKER.match(line)]


def parse_subquestions(text: str, original: str) -> list[str]:
    """모델 출력에서 하위 질문을 꺼낸다. 쓸 만한 것이 둘 미만이면 [원 질문]을 돌려준다."""
    seen: set[str] = set()
    questions: list[str] = []
    for raw in _candidates(text):
        item = _clean(raw)[:_MAX_QUESTION_CHARS]
        key = re.sub(r"\s+", "", item).lower()
        if len(item) < _MIN_QUESTION_CHARS or key in seen or adds_unasked_detail(item, original):
            continue
        seen.add(key)
        questions.append(item)
        if len(questions) == MAX_SUBQUESTIONS:
            break
    return questions if len(questions) >= 2 else [original]


def decompose(provider, query: str) -> list[str]:
    """하위 질문 목록. 모델 호출이 실패해도 예외를 던지지 않고 [원 질문]으로 이어 간다."""
    if not looks_compound(query):
        return [query]
    try:
        output = provider.generate(DECOMPOSE_SYSTEM_PROMPT, decompose_messages(query))
    except Exception:
        logger.exception("deep search: decomposition failed; searching the original question")
        return [query]
    return parse_subquestions(output, query)
