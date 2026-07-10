import base64

from cryptography.fernet import Fernet
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


def _get_fernet() -> Fernet:
    key_material = (settings.encryption_key or settings.secret_key).encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=_KDF_ITERATIONS,
    )
    fernet_key = base64.urlsafe_b64encode(kdf.derive(key_material))
    return Fernet(fernet_key)


def encrypt_secret(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
