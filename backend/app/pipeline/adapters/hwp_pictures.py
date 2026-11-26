"""HWP·HWPX 그림이 본문 어디에 박혀 있는지 읽는다(2026-11-23).

어댑터는 BinData 그림을 위치 없이 읽어 모두 1쪽에 두었다. 그래서 그림 글([그림 N])이 표지 바로 뒤에 몰렸다
(NS-AM 검사매뉴얼 그림 20·23·24·29·33). 본문을 읽는 순서대로 그림 컨트롤이 가리키는 BinData 를 남기고,
그림을 그 그림이 들어 있던 문단 뒤에 둔다. 쪽은 미리보기 쪽 나눔에서 그 문단의 쪽을 따라간다(process.py).

- HWP: 그림 컨트롤의 PictureInfo bindata-id 는 DocInfo BinData 목록의 순번(1부터)이고, 그 BinData 의
  BinDataEmbedding storage-id(BIN0001)가 BinData 스트림 이름(BIN0001.jpg)의 앞부분이다.
- HWPX: hc:img binaryItemIDRef 는 content.hpf 매니페스트 항목 id 이고, 그 href 가 BinData 파일이다.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from app.pipeline.adapters.base import RawImageRegion, RawTextBlock

# 본문에 놓인 자리. 문단·표 블록(그 뒤에 둔다), "start"(첫 블록 앞), None(자리를 모른다)
Anchor = RawTextBlock | str | None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def hwp_bin_stems(root) -> dict[str, str]:
    """bindata-id(1부터, 문자열) → BinData 스트림 이름 앞부분(BIN0001). 연결(link) 그림은 파일에 없어 뺀다."""
    stems: dict[str, str] = {}
    for number, bindata in enumerate(root.iter("BinData"), 1):
        embedding = bindata.find("BinDataEmbedding")
        storage_id = embedding.get("storage-id") if embedding is not None else None
        if storage_id:
            stems[str(number)] = storage_id
    return stems


def hwp_picture_refs(elem, bin_stems: dict[str, str]) -> list[str]:
    """요소 안의 그림이 가리키는 BinData 스트림 이름 앞부분을 문서 순서대로. 파일에 없는 그림은 뺀다."""
    refs = []
    for info in elem.iter("PictureInfo"):
        stem = bin_stems.get(info.get("bindata-id", ""))
        if stem:
            refs.append(stem)
    return refs


def hwpx_picture_refs(elem) -> list[str]:
    """요소 안 hc:img 의 binaryItemIDRef 를 문서 순서대로."""
    return [
        ref for node in elem.iter()
        if _local(node.tag) == "img" and (ref := node.get("binaryItemIDRef"))
    ]


def hwpx_manifest_stems(manifest: bytes) -> dict[str, str]:
    """content.hpf 매니페스트의 BinData 항목 id → 파일 이름 앞부분. 읽지 못하면 빈 사전(파일 이름으로 맞춘다)."""
    from app.core.safe_xml import parse_xml_bytes

    try:
        root = parse_xml_bytes(manifest)
    except Exception:
        return {}
    stems = {}
    for item in root.iter():
        href = item.get("href") or ""
        if _local(item.tag) == "item" and item.get("id") and href.startswith("BinData/"):
            stems[item.get("id")] = PurePosixPath(href).stem
    return stems


def anchored_image_regions(
    refs: list[str], anchors: list[tuple[int, Anchor]], named_images: list[tuple[str, bytes]],
) -> list[RawImageRegion]:
    """본문에 놓인 그림을 그 자리와 함께 문서 순서대로, 본문에 놓이지 않은 그림은 자리 없이 뒤에 낸다.

    refs 는 본문에서 만난 그림 참조, anchors 는 (refs 순번, 자리). 같은 그림을 여러 번 쓰면 처음 자리만 쓴다
    (그림 인식은 같은 그림을 한 번만 한다). 본문에 놓인 그림과 내용이 같은 자리 없는 사본은 버린다. 같은 그림을
    BinData 에 두 번 담은 HWP 에서 자리 없는 사본이 첫 쪽에 붙고, 그림 인식의 중복 제거가 그 사본을 남겨 5쪽 그림이
    1쪽에 나왔다(예측분석 설계보고서, 2026-11-26)."""
    data_by_stem: dict[str, bytes] = {}
    for stem, data in named_images:
        data_by_stem.setdefault(stem, data)
    regions: list[RawImageRegion] = []
    placed: set[str] = set()
    for ref_index, anchor in anchors:
        stem = refs[ref_index]
        if stem in placed or stem not in data_by_stem:
            continue
        placed.add(stem)
        regions.append(_region(data_by_stem[stem], anchor))
    placed_data = {region.image_bytes for region in regions}
    for stem, data in named_images:
        if stem not in placed and data not in placed_data:
            placed.add(stem)
            placed_data.add(data)
            regions.append(_region(data, None))
    return regions


def _region(data: bytes, anchor: Anchor) -> RawImageRegion:
    return RawImageRegion(page_number=1, bbox=(0, 0, 0, 0), image_bytes=data, anchor=anchor)
