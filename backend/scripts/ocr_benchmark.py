"""OCR 엔진 비교 벤치마크 — 텍스트 레이어가 있는 PDF 를 이미지로 렌더링(스캔 시뮬레이션)한 뒤 OCR 하고,
원본 텍스트 레이어를 정답으로 삼아 후보 엔진을 같은 기준으로 비교한다.

정답을 사람이 쓰지 않아도 되는 대신 한계가 있다: 렌더링 이미지는 실제 스캔보다 깨끗하다(기울기·노이즈 없음).
윤곽선(벡터)으로 글자를 그린 PDF 는 렌더링 결과가 이 이미지와 같아 OCR 난이도가 거의 같다.

사용: python scripts/ocr_benchmark.py --pdf a.pdf:1,2,3 --pdf b.pdf:5,6 [--engines tesseract_legacy,easyocr] [--retrieval]
지표: 4글자 조각 재현율/정밀도(공백 무시, 순서 무관), 문자 단위 유사도(SequenceMatcher), 한 글자 토큰 비율(글자 벌어짐),
      페이지당 시간. --retrieval 을 주면 RAG 관점의 검색 지표도 잰다: 원본 텍스트 레이어에서 뽑은 문장을 질문으로 삼아
      OCR 결과로 만든 페이지 색인에서 정답 페이지를 찾는 비율(hit@1, MRR) — 이 시스템의 목적(검색 가능한 텍스트)에 맞춘 판정 기준.
"""
import argparse
import difflib
import io
import re
import statistics
import time
from pathlib import Path

DPI = 300
NGRAM = 4
_SPACE_RE = re.compile(r"\s+")
TRUTH = "정답(텍스트 레이어)"


def normalize(text: str) -> str:
    return _SPACE_RE.sub("", text or "")


def _ngrams(text: str, n: int = NGRAM) -> set[str]:
    return {text[i:i + n] for i in range(len(text) - n + 1)}


def single_char_token_ratio(text: str) -> float:
    """공백 기준 토큰 중 한글 한 글자짜리 비율 — OCR 이 글자 사이를 벌려 놓았는지 보는 지표."""
    tokens = (text or "").split()
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if re.fullmatch(r"[가-힣]", t)) / len(tokens)


def score(gt: str, ocr: str) -> dict:
    g, o = normalize(gt), normalize(ocr)
    gg, og = _ngrams(g), _ngrams(o)
    recall = len(gg & og) / len(gg) if gg else float("nan")
    precision = len(gg & og) / len(og) if og else 0.0
    f1 = 2 * recall * precision / (recall + precision) if recall and precision else 0.0
    similarity = difflib.SequenceMatcher(None, g, o, autojunk=False).ratio() if g else float("nan")
    return {"recall": recall, "precision": precision, "f1": f1, "similarity": similarity,
            "single_char": single_char_token_ratio(ocr)}


# ── 후보 엔진 ────────────────────────────────────────────────────────────────
def _tesseract(image, psm: int, binarize: bool) -> str:
    import pytesseract

    from app.pipeline.adapters.pdf_adapter import _preprocess_for_ocr

    # 운영(_ocr_page_with_confidence)도 본문은 image_to_string 결과를 쓰므로 같은 경로다.
    # (과거 운영은 image_to_data 단어를 이어 붙여 한글이 음절 단위로 벌어졌다 — 표의 "이전 운영" 행.)
    prepared = _preprocess_for_ocr(image) if binarize else image.convert("L")
    return pytesseract.image_to_string(prepared, lang="kor+eng", config=f"--oem 1 --psm {psm}")


_EASY = {}


def _easyocr(image) -> str:
    import numpy as np

    if "r" not in _EASY:
        import easyocr

        _EASY["r"] = easyocr.Reader(["ko", "en"], gpu=True, verbose=False)
    result = _EASY["r"].readtext(np.asarray(image.convert("RGB")), detail=1, paragraph=False)
    # 위→아래, 왼→오른쪽으로 줄을 만든다
    boxes = sorted(((min(p[1] for p in b), min(p[0] for p in b), t) for b, t, _c in result))
    lines, current, last_y = [], [], None
    for y, x, t in boxes:
        if last_y is not None and abs(y - last_y) > 14:
            lines.append(" ".join(current))
            current = []
        current.append(t)
        last_y = y
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


ENGINES = {
    "tesseract_legacy": lambda im: _tesseract(im, 3, True),         # 현재 운영
    "tesseract_gray_psm3": lambda im: _tesseract(im, 3, False),     # 이진화 없이
    "tesseract_gray_psm6": lambda im: _tesseract(im, 6, False),     # 단일 블록 가정
    "tesseract_gray_psm4": lambda im: _tesseract(im, 4, False),     # 단일 열 가변 크기
    "tesseract_gray_psm1": lambda im: _tesseract(im, 1, False),     # 자동 + 방향 감지
    "tesseract_bin_psm6": lambda im: _tesseract(im, 6, True),       # 이진화 + psm6
    "tesseract_bin_psm4": lambda im: _tesseract(im, 4, True),       # 이진화 + psm4
    "easyocr": _easyocr,
}


def page_images_and_truth(pdf_path: str, pages: list[int]):
    import fitz
    from PIL import Image

    with fitz.open(pdf_path) as pdf:
        for number in pages:
            page = pdf[number - 1]
            truth = page.get_text()
            image = Image.open(io.BytesIO(page.get_pixmap(dpi=DPI).tobytes("png")))
            yield number, truth, image


def pick_queries(truth: str, count: int = 2) -> list[str]:
    """정답 텍스트에서 질문으로 쓸 문장(줄)을 고른다 — 한글이 충분하지 않은 줄은 제외."""
    lines = [line.strip() for line in truth.splitlines()]
    usable = [line for line in lines if 25 <= len(line) <= 90 and len(re.findall(r"[가-힣]", line)) >= 12]
    if not usable:
        return []
    step = max(1, len(usable) // count)
    return usable[::step][:count]


def retrieval_scores(pages: list[dict], texts: dict[str, str], model_key: str) -> dict:
    """pages: [{id, queries}], texts: 페이지 id → 색인할 텍스트. 질문마다 코사인 유사도 순위로 정답 페이지를 찾는다."""
    import numpy as np

    from app.services.embedding import get_embedding_provider

    provider = get_embedding_provider(model_key)
    ids = [p["id"] for p in pages]
    doc_vecs = np.array(provider.embed([texts[i][:3000] or " " for i in ids]))
    doc_vecs /= np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-9
    hits = rr = total = 0
    for page in pages:
        for q in page["queries"]:
            qv = np.array(provider.embed([q])[0])
            qv /= np.linalg.norm(qv) + 1e-9
            order = list(np.argsort(-(doc_vecs @ qv)))
            rank = order.index(ids.index(page["id"])) + 1
            total += 1
            hits += rank == 1
            rr += 1.0 / rank
    return {"hit1": hits / total if total else float("nan"), "mrr": rr / total if total else float("nan"), "queries": total}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", action="append", required=True, help="경로:쪽번호,쪽번호,...")
    parser.add_argument("--engines", default=",".join(ENGINES))
    parser.add_argument("--retrieval", action="store_true", help="RAG 검색 지표(hit@1, MRR)도 계산")
    parser.add_argument("--embedding-model", default="bge-m3")
    args = parser.parse_args()
    names = args.engines.split(",")

    rows: dict[str, list[dict]] = {n: [] for n in names}
    texts: dict[str, dict[str, str]] = {n: {} for n in [TRUTH, *names]}
    pages_meta: list[dict] = []
    for spec in args.pdf:
        path, _, pages = spec.partition(":")
        for number, truth, image in page_images_and_truth(path, [int(p) for p in pages.split(",")]):
            if len(normalize(truth)) < 200:
                continue  # 정답 글자가 너무 적은 쪽은 제외
            page_id = f"{Path(path).name[:14]}#{number}"
            pages_meta.append({"id": page_id, "queries": pick_queries(truth)})
            texts[TRUTH][page_id] = truth
            for name in names:
                started = time.time()
                text = ENGINES[name](image)
                elapsed = time.time() - started
                texts[name][page_id] = text
                rows[name].append({**score(truth, text), "seconds": elapsed})
                print(f"  {name:20} {page_id:20} f1={rows[name][-1]['f1']:.3f} sim={rows[name][-1]['similarity']:.3f} "
                      f"single={rows[name][-1]['single_char']:.2f} {elapsed:.1f}s", flush=True)

    retrieval = {}
    if args.retrieval:
        for name in [TRUTH, *names]:
            retrieval[name] = retrieval_scores(pages_meta, texts[name], args.embedding_model)

    header = "엔진                  쪽수  재현율  정밀도     F1  유사도  한글자토큰  초/쪽"
    print("\n" + header + ("  검색hit@1   MRR" if retrieval else ""))
    if retrieval:
        c = retrieval[TRUTH]
        print(f"{'정답(상한)':20} {'':>5} {'':>7} {'':>7} {'':>6} {'':>7} {'':>10} {'':>6}  "
              f"{c['hit1']:>9.2f} {c['mrr']:>5.2f}  (질문 {c['queries']}개)")
    for name in names:
        r = rows[name]
        if not r:
            continue

        def m(key: str) -> float:
            return statistics.mean(x[key] for x in r)

        line = (f"{name:20} {len(r):>5} {m('recall'):>7.3f} {m('precision'):>7.3f} {m('f1'):>6.3f} "
                f"{m('similarity'):>7.3f} {m('single_char'):>10.2f} {m('seconds'):>6.1f}")
        if retrieval:
            line += f"  {retrieval[name]['hit1']:>9.2f} {retrieval[name]['mrr']:>5.2f}"
        print(line)


if __name__ == "__main__":
    main()
