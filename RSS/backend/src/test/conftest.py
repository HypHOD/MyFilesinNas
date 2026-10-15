import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

import module.models  # noqa: F401  导入以注册所有表元数据

# Settings 单例在首次 import module.conf 时按 cwd 落盘 config/ 与 data/，
# 测试期间把 cwd 切到临时目录做隔离
_TEST_CWD = tempfile.mkdtemp(prefix="rss-test-")

_RSS_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "mikan_rss.xml"


def pytest_configure(config):
    """在收集/导入任何 module.* 之前切到隔离 cwd。

    必须放在 configure 钩子而非模块顶层：模块顶层的 chdir 会干扰 pytest
    以相对路径解析 testpaths。
    """
    os.chdir(_TEST_CWD)


@pytest_asyncio.fixture
async def db_engine(tmp_path):
    """独占临时文件的异步引擎（内存库对异步多连接不可靠，用文件库）。"""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _reset_network_state():
    """用例间隔离网络层共享客户端（MockTransport 注入后必须重置）。"""
    import module.network.request_url as request_url_module

    request_url_module._transport_override = None
    await request_url_module.reset_shared_client()
    yield
    request_url_module._transport_override = None
    await request_url_module.reset_shared_client()


@pytest_asyncio.fixture(autouse=True)
async def _reset_downloader_state():
    """用例间隔离下载器门面缓存（含具体客户端的连接池与会话）。"""
    import module.downloader.download_client as download_client_module

    await download_client_module.shutdown()
    download_client_module._reset_client_cache()
    yield
    await download_client_module.shutdown()
    download_client_module._reset_client_cache()


@pytest.fixture
def mock_downloader_settings(monkeypatch):
    """把下载器类型切到 mock（门面与循环都经 settings 单例取配置）。"""
    from module.conf import settings

    monkeypatch.setattr(settings.downloader, "type", "mock")


@pytest_asyncio.fixture
async def _bind_global_database(tmp_path, monkeypatch):
    """把无参 ``Database()``（loops / AppContext 的取库方式）绑到临时文件库。

    必须同时替换 ``combine.async_engine`` 与 ``combine.async_session_factory``
    ——前者供 create_table、后者供每次开 session（Database 各自引用的是
    combine 命名空间里的名字）；NullPool 避免连接池在 tmp_path 清理后
    仍持有文件句柄。测试内直接用 ``async with Database() as db:`` 断言。
    """
    import module.database.combine as combine

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/global.db", poolclass=NullPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    monkeypatch.setattr(combine, "async_engine", engine)
    monkeypatch.setattr(
        combine,
        "async_session_factory",
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )
    yield engine
    await engine.dispose()


@pytest.fixture
def rss_transport():
    """把网络层传输替换为返回本地 mikan RSS fixture 的 MockTransport。

    autouse 的 _reset_network_state 会在用例前后清理注入。
    """
    import httpx

    import module.network.request_url as request_url_module

    content = _RSS_FIXTURE_PATH.read_bytes()

    def handler(request):
        return httpx.Response(200, content=content)

    request_url_module._transport_override = httpx.MockTransport(handler)
    return content
