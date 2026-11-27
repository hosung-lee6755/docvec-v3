from app.pipeline.adapters.docling_toc import toc_columns


def _line(*words):
    return [(x, 0, x + 10, 10, text) for x, text in words]


def test_toc_columns_keeps_page_number_tail_drops_body_and_collects_side_entries():
    # Pub120bk 490쪽: 차례 상자 옆 단 본문("The terrain is…")이 같은 높이에 있어 한 줄로 섞였다(2026-11-26)
    lines = [
        _line((60, "General"), (100, "....")),
        _line((60, "Search"), (90, "and"), (110, "Rescue"), (320, "The"), (340, "terrain"), (380, "is"), (400, "Kharst")),
        _line((60, "Currency"), (320, "Time"), (345, "Zone"), (380, "298")),
        _line((60, "Index"), (310, "312")),
    ]

    main, side = toc_columns(lines, right_edge=300)

    assert main == ["General ....", "Search and Rescue", "Currency", "Index 312"]
    assert side == ["Time Zone 298"]
