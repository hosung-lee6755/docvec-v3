from app.pipeline.blocks.table_markdown import rows_to_markdown


def test_renders_normal_table_with_header_and_separator():
    rows = [["Name", "Age"], ["Kim", "20"], ["Lee", "31"]]

    md = rows_to_markdown(rows)

    lines = md.split("\n")
    assert lines[0] == "| Name | Age |"
    assert lines[1] == "|---|---|"
    assert lines[2] == "| Kim | 20 |"
    assert lines[3] == "| Lee | 31 |"


def test_renders_empty_cells_as_blank_and_pads_short_rows():
    rows = [["A", "B", "C"], ["1", "", "3"], ["only-one"]]

    md = rows_to_markdown(rows)

    lines = md.split("\n")
    assert lines[2] == "| 1 |  | 3 |"
    assert lines[3] == "| only-one |  |  |"


def test_renders_header_only_table_with_valid_separator():
    rows = [["Col1", "Col2"]]

    md = rows_to_markdown(rows)

    assert md == "| Col1 | Col2 |\n|---|---|"


def test_returns_empty_string_for_no_rows():
    assert rows_to_markdown([]) == ""
