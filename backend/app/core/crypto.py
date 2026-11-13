import base64
from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.config import settings

# PBKDF2 here derives a single symmetric Fernet key from one shared secret
# (not a per-user password), so there's no per-record salt to persist — this
# fixed, non-secret salt only adds domain separation and forces brute-force
# attempts against the underlying secret_key/encryption_key to pay the full
# iteration cost instead of a precomputed SHA256 rainbow table (the previous
# implementation's weakness).
_KDF_SALT = b"docvec-api-key-encryption-v1"
_KDF_ITERATIONS = 390_000


@lru_cache(maxsize=8)
def _derive_fernet(key_material: str) -> Fernet:
    # 키 유도는 39만 번 반복이라 한 번에 0.3초 안팎 걸린다. 같은 키로 매번 다시 유도하지 않게 캐시한다
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=_KDF_ITERATIONS,
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(key_material.encode("utf-8"))))


def _current_key_material() -> str:
    return settings.encryption_key or settings.secret_key


def _previous_key_materials() -> list[str]:
    current = _current_key_material()
    raw = settings.encryption_keys_previous or ""
    return [k.strip() for k in raw.split(",") if k.strip() and k.strip() != current]


def _get_fernet() -> MultiFernet:
    """현재 키로 암호화하고, 복호화는 현재 키와 예전 키를 차례로 시도한다."""
    keys = [_current_key_material(), *_previous_key_materials()]
    return MultiFernet([_derive_fernet(k) for k in keys])


def encrypt_secret(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def is_current_key(ciphertext: str) -> bool:
    """현재 키만으로 풀리는가. 예전 키로만 풀리면 다시 암호화할 대상이다."""
    try:
        _derive_fernet(_current_key_material()).decrypt(ciphertext.encode("utf-8"))
        return True
    except Exception:  # noqa: BLE001 - InvalidToken 외 형식 오류도 "현재 키 아님"으로 본다
        return False


def rotate_secret(ciphertext: str) -> str:
    """어느 키로 암호화됐든 현재 키로 다시 암호화한다. 어떤 키로도 풀리지 않으면 InvalidToken."""
    return _get_fernet().rotate(ciphertext.encode("utf-8")).decode("utf-8")
