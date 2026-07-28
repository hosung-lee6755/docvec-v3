from app.pipeline.blocks.extraction_blocks import _match_image_paths


def test_picture_element_matched_to_same_page_image():
    elements = [{"id": "el-1", "page": 2, "type": "picture", "metadata": {}}]
    image_records = [{"page_number": 2, "storage_key": "images/fig-1.png"}]

    _match_image_paths(elements, image_records)

    assert elements[0]["metadata"]["image_path"] == "images/fig-1.png"


def test_non_picture_elements_are_untouched():
    elements = [{"id": "el-1", "page": 2, "type": "table", "metadata": {}}]
    image_records = [{"page_number": 2, "storage_key": "images/fig-1.png"}]

    _match_image_paths(elements, image_records)

    assert "image_path" not in elements[0]["metadata"]


def test_no_matching_page_leaves_image_path_unset():
    elements = [{"id": "el-1", "page": 5, "type": "picture", "metadata": {}}]
    image_records = [{"page_number": 2, "storage_key": "images/fig-1.png"}]

    _match_image_paths(elements, image_records)

    assert "image_path" not in elements[0]["metadata"]


def test_multiple_pictures_on_same_page_consume_candidates_in_order():
    elements = [
        {"id": "el-1", "page": 3, "type": "picture", "metadata": {}},
        {"id": "el-2", "page": 3, "type": "picture", "metadata": {}},
    ]
    image_records = [
        {"page_number": 3, "storage_key": "images/first.png"},
        {"page_number": 3, "storage_key": "images/second.png"},
    ]

    _match_image_paths(elements, image_records)

    assert elements[0]["metadata"]["image_path"] == "images/first.png"
    assert elements[1]["metadata"]["image_path"] == "images/second.png"


def test_more_pictures_than_images_leaves_extras_unset():
    elements = [
        {"id": "el-1", "page": 1, "type": "picture", "metadata": {}},
        {"id": "el-2", "page": 1, "type": "picture", "metadata": {}},
    ]
    image_records = [{"page_number": 1, "storage_key": "images/only.png"}]

    _match_image_paths(elements, image_records)

    assert elements[0]["metadata"]["image_path"] == "images/only.png"
    assert "image_path" not in elements[1]["metadata"]
