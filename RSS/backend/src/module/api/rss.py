from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from module.database import Database, get_db
from module.models import APIResponse, RSSItem, RSSUpdate

router = APIRouter(prefix="/rss", tags=["rss"])


@router.get("", response_model=list[RSSItem])
async def get_rss(db: Database = Depends(get_db)):
    return await db.rss.search_all()


@router.post("/add", response_model=APIResponse)
async def add_rss(rss: RSSItem, db: Database = Depends(get_db)):
    if await db.rss.search_url(rss.url):
        return JSONResponse(
            status_code=400,
            content={"msg_en": "RSS already exists.", "msg_zh": "RSS 已存在。"},
        )
    await db.rss.add(rss)
    return JSONResponse(
        status_code=200,
        content={"msg_en": "Add RSS successfully.", "msg_zh": "添加 RSS 成功。"},
    )


@router.patch("/enable/{rss_id}", response_model=APIResponse)
async def enable_rss(rss_id: int, db: Database = Depends(get_db)):
    if await db.rss.enable(rss_id):
        return JSONResponse(
            status_code=200,
            content={"msg_en": "Enable RSS successfully.", "msg_zh": "启用 RSS 成功。"},
        )
    return JSONResponse(
        status_code=404,
        content={"msg_en": "Enable RSS failed.", "msg_zh": "启用 RSS 失败。"},
    )


@router.patch("/disable/{rss_id}", response_model=APIResponse)
async def disable_rss(rss_id: int, db: Database = Depends(get_db)):
    if await db.rss.disable(rss_id):
        return JSONResponse(
            status_code=200,
            content={
                "msg_en": "Disable RSS successfully.",
                "msg_zh": "禁用 RSS 成功。",
            },
        )
    return JSONResponse(
        status_code=404,
        content={"msg_en": "Disable RSS failed.", "msg_zh": "禁用 RSS 失败。"},
    )


@router.patch("/update/{rss_id}", response_model=APIResponse)
async def update_rss(rss_id: int, data: RSSUpdate, db: Database = Depends(get_db)):
    if await db.rss.update(rss_id, data):
        return JSONResponse(
            status_code=200,
            content={"msg_en": "Update RSS successfully.", "msg_zh": "更新 RSS 成功。"},
        )
    return JSONResponse(
        status_code=404,
        content={"msg_en": "Update RSS failed.", "msg_zh": "更新 RSS 失败。"},
    )


@router.delete("/delete/{rss_id}", response_model=APIResponse)
async def delete_rss(rss_id: int, db: Database = Depends(get_db)):
    if await db.rss.delete(rss_id):
        return JSONResponse(
            status_code=200,
            content={"msg_en": "Delete RSS successfully.", "msg_zh": "删除 RSS 成功。"},
        )
    return JSONResponse(
        status_code=404,
        content={"msg_en": "Delete RSS failed.", "msg_zh": "删除 RSS 失败。"},
    )
