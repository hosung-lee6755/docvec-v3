"""SMB 파일 서버 접근 어댑터(v3 마일스톤 3).

smbprotocol을 직접 다루는 코드는 이 모듈에만 둔다. 동기화 엔진은 `SourceClient` 프로토콜만 쓴다.

- 연결은 커넥터마다 별도 connection_cache를 쓴다. smbclient의 전역 세션 캐시에 자격 증명이
  섞이지 않게 하기 위해서다.
- 원격 경로는 공유 루트 기준 상대 경로("a/b.pdf")로 바꾼다. "..", 콜론, NUL이 든 이름은 버린다.
- 보안 설명자는 QUERY_INFO(SMB2_0_INFO_SECURITY)로 원본 바이트를 받는다. 해석은 acl_mapping이 한다.
"""
from __future__ import annotations

import posixpath
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

_OWNER_GROUP_DACL = 0x1 | 0x2 | 0x4
_SECURITY_INFO = 3
_MAX_SD_BYTES = 64 * 1024


class FileTooLarge(Exception):
    pass


class SourceUnavailable(Exception):
    """파일 서버에 연결하거나 로그인하지 못했다."""


@dataclass(frozen=True)
class RemoteFile:
    path: str
    size: int
    mtime: float


class SourceClient(Protocol):
    def list_files(self) -> Iterator[RemoteFile]: ...
    def read_file(self, path: str, max_bytes: int) -> bytes: ...
    def read_security_descriptor(self, path: str) -> bytes: ...
    def close(self) -> None: ...


def safe_relative_path(parts: list[str]) -> str | None:
    """원격 이름 조각을 상대 경로로 합친다. 위험한 이름이 있으면 None."""
    clean = []
    for part in parts:
        if not part or part in (".", "..") or any(c in part for c in ":\x00/\\"):
            return None
        clean.append(part)
    return posixpath.join(*clean) if clean else None


class SmbSourceClient:
    def __init__(self, host: str, share: str, username: str, password: str, *, port: int = 445,
                 base_path: str = ""):
        import smbclient

        self._smb = smbclient
        self._cache: dict = {}
        base = "\\".join(p for p in base_path.replace("/", "\\").split("\\") if p)
        self._root = rf"\\{host}\{share}" + (rf"\{base}" if base else "")
        try:
            smbclient.register_session(
                host, username=username, password=password, port=port, connection_cache=self._cache,
            )
        except Exception as exc:  # smbprotocol은 연결·인증 실패를 여러 예외로 던진다
            raise SourceUnavailable(type(exc).__name__) from exc

    def _remote(self, path: str) -> str:
        parts = path.split("/")
        if safe_relative_path(parts) is None:
            raise ValueError("unsafe path")
        return self._root + "\\" + "\\".join(parts)

    def list_files(self) -> Iterator[RemoteFile]:
        root_len = len(self._root)
        def _raise(exc: OSError) -> None:
            # os.walk처럼 기본값은 하위 폴더 오류를 삼킨다. 그러면 못 읽은 폴더의 파일이 "삭제됨"으로 보인다.
            raise exc

        for dirpath, _dirs, names in self._smb.walk(self._root, onerror=_raise, connection_cache=self._cache):
            rel_dir = [p for p in dirpath[root_len:].split("\\") if p]
            for name in names:
                rel = safe_relative_path(rel_dir + [name])
                if rel is None:
                    continue
                st = self._smb.stat(dirpath + "\\" + name, connection_cache=self._cache)
                yield RemoteFile(path=rel, size=int(st.st_size), mtime=float(st.st_mtime))

    def read_file(self, path: str, max_bytes: int) -> bytes:
        with self._smb.open_file(self._remote(path), mode="rb", connection_cache=self._cache) as fh:
            data = fh.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise FileTooLarge(path)
        return data

    def read_security_descriptor(self, path: str) -> bytes:
        from smbclient._io import SMBFileTransaction, SMBRawIO
        from smbprotocol.open import FilePipePrinterAccessMask, SMB2QueryInfoRequest, SMB2QueryInfoResponse

        raw = SMBRawIO(
            self._remote(path), mode="r", desired_access=FilePipePrinterAccessMask.READ_CONTROL,
            connection_cache=self._cache,
        )
        with SMBFileTransaction(raw) as tx:
            req = SMB2QueryInfoRequest()
            req["info_type"] = _SECURITY_INFO
            req["file_info_class"] = 0
            req["additional_information"] = _OWNER_GROUP_DACL
            req["output_buffer_length"] = _MAX_SD_BYTES
            req["file_id"] = tx.raw.fd.file_id

            def _receive(request):
                response = tx.raw.fd.connection.receive(request)
                parsed = SMB2QueryInfoResponse()
                parsed.unpack(response["data"].get_value())
                return parsed["buffer"].get_value()

            tx += (req, _receive)
        return bytes(tx.results[0])

    def close(self) -> None:
        try:
            self._smb.reset_connection_cache(fail_on_error=False, connection_cache=self._cache)
        except Exception:  # 닫기 실패는 동기화 결과에 영향을 주지 않는다
            pass
