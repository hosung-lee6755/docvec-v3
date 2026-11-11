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
        if len(item) < _MIN_QUESTION_CHARS or key in seen:
            continue
        seen.add(key)
        questions.append(item)
        if len(questions) == MAX_SUBQUESTIONS:
            break
    return questions if len(questions) >= 2 else [original]


def decompose(provider, query: str) -> list[str]:
    """하위 질문 목록. 모델 호출이 실패해도 예외를 던지지 않고 [원 질문]으로 이어 간다."""
    try:
        output = provider.generate(DECOMPOSE_SYSTEM_PROMPT, decompose_messages(query))
    except Exception:
        logger.exception("deep search: decomposition failed; searching the original question")
        return [query]
    return parse_subquestions(output, query)
