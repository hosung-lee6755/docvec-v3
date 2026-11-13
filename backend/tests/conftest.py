import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.db.base import Base

TEST_DATABASE_URL = "postgresql+asyncpg://docvec:docvec_secret@localhost:5432/docvec_test"

@pytest_asyncio.fixture(scope="session")
async def engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest_asyncio.fixture
async def db_session(engine):
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        async with session.begin():
            yield session
            await session.rollback()


@pytest.fixture(autouse=True)
def _directory_login_off_by_default(monkeypatch):
    """개발 컨테이너의 .env에 LDAP_ENABLED=true가 있어도 테스트는 꺼진 상태에서 시작한다.
    AD 로그인을 시험하는 테스트는 각자 켠다."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ldap_enabled", False)
    # 기존 회원가입 테스트는 가입이 열린 상태를 전제로 한다. 꺼진 동작은 test_auth_local_accounts가 따로 시험한다
    monkeypatch.setattr(settings, "self_signup_enabled", True)
