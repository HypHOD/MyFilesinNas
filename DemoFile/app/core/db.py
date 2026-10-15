from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = "sqlite:///./zfile.db"

engine = create_engine(
    DATABASE_URL,
    # SQLite 默认禁止连接跨线程使用；FastAPI 的 def 路由跑在线程池里，不加这行会报错
    connect_args={"check_same_thread": False},
    echo=False,  # 想看 SQL 就改成 True
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
