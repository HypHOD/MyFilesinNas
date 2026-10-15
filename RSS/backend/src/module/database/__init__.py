from .combine import Database


async def get_db():
    """FastAPI 依赖：请求级异步 Database。"""
    async with Database() as db:
        yield db


__all__ = ["Database", "get_db"]
