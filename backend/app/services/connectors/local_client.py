"""서버 로컬 폴더 커넥터(AD와 파일 서버가 없는 회사).

서버(컨테이너)에 마운트한 폴더를 읽는다. 관리자가 고를 수 있는 폴더는 `CONNECTOR_LOCAL_ROOT` 아래로
제한한다. 등록할 때와 읽을 때 모두 실제 경로(realpath)로 확인해 심볼릭 링크로 루트 밖에 나가지 못하게 한다.
파일 권한 정보가 없으므로 이 커넥터는 항상 "컬렉션 권한만 적용" 방식으로 동기화한다.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

from app.services.connectors.smb_client import FileTooLarge, RemoteFile, SourceUnavailable, safe_relative_path


class LocalPathError(ValueError):
    """허용한 루트 밖이거나 없는 폴더다."""


def _inside(root: str, path: str) -> bool:
    return os.path.commonpath([root, path]) == root


def resolve_local_folder(root: str, folder: str) -> str:
    """루트 기준 상대 폴더를 실제 경로로 바꾼다. 루트 밖이거나 폴더가 아니면 LocalPathError."""
    parts = [p for p in (folder or "").replace("\\", "/").split("/") if p]
    if not parts or safe_relative_path(parts) is None:
        raise LocalPathError("폴더는 원천 루트 아래의 상대 경로로 적으세요. '..'이나 드라이브 문자는 쓸 수 없습니다.")
    real_root = os.path.realpath(root)
    target = os.path.realpath(os.path.join(real_root, *parts))
    if not _inside(real_root, target) or target == real_root:
        raise LocalPathError("원천 루트 밖의 폴더는 쓸 수 없습니다.")
    if not os.path.isdir(target):
        raise LocalPathError(f"폴더를 찾을 수 없습니다: {'/'.join(parts)}")
    return target


class LocalSourceClient:
    def __init__(self, root: str, folder: str):
        try:
            self._base = resolve_local_folder(root, folder)
        except LocalPathError as exc:
            raise SourceUnavailable(str(exc)) from exc

    def _path(self, relative: str) -> str:
        parts = relative.split("/")
        if safe_relative_path(parts) is None:
            raise ValueError("unsafe path")
        target = os.path.realpath(os.path.join(self._base, *parts))
        if not _inside(self._base, target):
            raise ValueError("unsafe path")
        return target

    def list_files(self) -> Iterator[RemoteFile]:
        def _raise(exc: OSError) -> None:
            # 읽지 못한 폴더를 건너뛰면 그 안의 파일이 "삭제됨"으로 보인다. 실행 전체를 실패로 둔다.
            raise exc

        for dirpath, dirs, names in os.walk(self._base, onerror=_raise, followlinks=False):
            dirs.sort()
            rel_dir = os.path.relpath(dirpath, self._base)
            rel_parts = [] if rel_dir == "." else rel_dir.split(os.sep)
            for name in sorted(names):
                full = os.path.join(dirpath, name)
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                rel = safe_relative_path(rel_parts + [name])
                if rel is None:
                    continue
                st = os.stat(full)
                yield RemoteFile(path=rel, size=int(st.st_size), mtime=float(st.st_mtime))

    def read_file(self, path: str, max_bytes: int) -> bytes:
        with open(self._path(path), "rb") as fh:
            data = fh.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise FileTooLarge(path)
        return data

    def read_security_descriptor(self, path: str) -> bytes:
        raise NotImplementedError("로컬 폴더에는 파일 서버 권한이 없습니다. 컬렉션 권한만 적용합니다.")

    def close(self) -> None:
        return None
