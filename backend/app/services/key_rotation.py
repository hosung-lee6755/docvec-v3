"""암호화 키 교체 — 저장된 암호문을 모두 현재 ENCRYPTION_KEY로 다시 암호화한다.

절차(유지보수 가이드 1.10):
1. 새 키를 ENCRYPTION_KEY에, 지금까지 쓰던 키를 ENCRYPTION_KEYS_PREVIOUS에 넣고 api·worker를 다시 만든다.
   이때부터 새로 쓰는 값은 새 키로 암호화되고, 기존 값은 예전 키로 계속 읽힌다.
2. scripts.rotate_encryption_key 를 --dry-run 으로 돌려 대상 수와 읽지 못하는 값을 확인한 뒤 실제로 돌린다.
3. 남은 대상이 0이면 ENCRYPTION_KEYS_PREVIOUS를 비우고 다시 만든다.
"""
from dataclasses import dataclass, field

from cryptography.fernet import InvalidToken
from sqlalchemy import select

from app.core.crypto import is_current_key, rotate_secret
from app.db.models.pii_detection import PiiDetection
from app.db.models.project_api_key import ProjectApiKey
from app.db.models.source_connector import SourceConnector
from app.db.models.user_api_key import UserApiKey

# (모델, 암호문 컬럼 이름). 새 암호화 컬럼을 만들면 여기에 넣는다
ENCRYPTED_COLUMNS = [
    (UserApiKey, "encrypted_key"),
    (ProjectApiKey, "encrypted_key"),
    (SourceConnector, "password_encrypted"),
    (PiiDetection, "original_encrypted"),
]


@dataclass
class RotationStats:
    checked: int = 0
    current: int = 0
    rotated: int = 0
    unreadable: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"checked": self.checked, "current": self.current, "rotated": self.rotated,
                "unreadable": len(self.unreadable)}


def rotate_all(db, *, dry_run: bool = True, batch_size: int = 500) -> dict[str, RotationStats]:
    """테이블별 결과. dry_run이면 바꾸지 않고 다시 암호화할 수를 센다(rotated에 센다)."""
    report: dict[str, RotationStats] = {}
    for model, column in ENCRYPTED_COLUMNS:
        stats = RotationStats()
        attr = getattr(model, column)
        last_id = None
        while True:
            stmt = select(model).where(attr.is_not(None), attr != "").order_by(model.id).limit(batch_size)
            if last_id is not None:
                stmt = stmt.where(model.id > last_id)
            rows = db.scalars(stmt).all()
            if not rows:
                break
            for row in rows:
                stats.checked += 1
                value = getattr(row, column)
                if is_current_key(value):
                    stats.current += 1
                    continue
                try:
                    rotated = rotate_secret(value)
                except InvalidToken:
                    stats.unreadable.append(str(row.id))
                    continue
                stats.rotated += 1
                if not dry_run:
                    setattr(row, column, rotated)
            last_id = rows[-1].id
            if not dry_run:
                db.commit()
        report[f"{model.__tablename__}.{column}"] = stats
    return report
