from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from module.conf import DATA_PATH

# SQLite 文件所在目录必须先存在，否则首次连接会报 unable to open database
Path("data").mkdir(parents=True, exist_ok=True)

ASYNC_DATA_PATH = DATA_PATH.replace("sqlite:///", "sqlite+aiosqlite:///")
# 「数据库底层连接管理」和「业务事务（Session）」解耦
# 依靠连接池一定程度提高并发度、但是受限于sqlite文件存取的文件锁限制
async_engine = create_async_engine(ASYNC_DATA_PATH)
async_session_factory = async_sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)


def _set_sqlite_pragmas(dbapi_conn, connection_record) -> None:
    """每个连接的 SQLite pragma
    多个 aiosqlite 连接并发读写: WAL 配合 busy_timeout; 写冲突时等待而非立刻抛 database is locked
    解决短时间内并发抛错问题
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


event.listen(async_engine.sync_engine, "connect", _set_sqlite_pragmas)
