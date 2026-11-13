"""서버 로컬 폴더 커넥터: 허용한 루트 밖으로 나가지 못하고, 파일 목록과 내용을 읽는다."""
import os

import pytest

from app.services.connectors import local_client as lc
from app.services.connectors.smb_client import FileTooLarge


@pytest.fixture
def root(tmp_path):
    base = tmp_path / "sources"
    (base / "영업" / "2026").mkdir(parents=True)
    (base / "영업" / "2026" / "계획.pdf").write_bytes(b"plan")
    (base / "영업" / "공지.hwp").write_bytes(b"notice")
    (tmp_path / "outside.pdf").write_bytes(b"secret")
    return base


def test_resolve_accepts_folders_inside_the_root(root):
    assert lc.resolve_local_folder(str(root), "영업") == os.path.realpath(root / "영업")


@pytest.mark.parametrize("bad", ["", "../", "영업/../..", "/etc", "C:/Windows", "없는폴더"])
def test_resolve_refuses_paths_outside_the_root_or_missing(root, bad):
    with pytest.raises(lc.LocalPathError):
        lc.resolve_local_folder(str(root), bad)


def test_resolve_refuses_symlinks_that_escape_the_root(root, tmp_path):
    link = root / "탈출"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlink not permitted")
    with pytest.raises(lc.LocalPathError):
        lc.resolve_local_folder(str(root), "탈출")


def test_lists_and_reads_files_with_relative_paths(root):
    client = lc.LocalSourceClient(str(root), "영업")

    files = {f.path: f.size for f in client.list_files()}

    assert files == {"2026/계획.pdf": 4, "공지.hwp": 6}
    assert client.read_file("2026/계획.pdf", 100) == b"plan"
    with pytest.raises(FileTooLarge):
        client.read_file("공지.hwp", 3)


def test_reading_outside_the_folder_is_refused(root):
    client = lc.LocalSourceClient(str(root), "영업")
    with pytest.raises(ValueError):
        client.read_file("../../outside.pdf", 100)


def test_symlinked_files_are_not_listed(root, tmp_path):
    try:
        (root / "영업" / "링크.pdf").symlink_to(tmp_path / "outside.pdf")
    except OSError:
        pytest.skip("symlink not permitted")
    client = lc.LocalSourceClient(str(root), "영업")
    assert "링크.pdf" not in {f.path for f in client.list_files()}


def test_local_folders_have_no_file_permissions(root):
    with pytest.raises(NotImplementedError):
        lc.LocalSourceClient(str(root), "영업").read_security_descriptor("공지.hwp")
