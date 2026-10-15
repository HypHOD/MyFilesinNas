from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from module.database import Database, get_db
from module.models import APIResponse, Bangumi, BangumiUpdate

router = APIRouter(prefix="/bangumi", tags=["bangumi"])


@router.get("", response_model=list[Bangumi])
async def get_bangumi(db: Database = Depends(get_db)):
    return await db.bangumi.search_all()


@router.get("/get/{bangumi_id}", response_model=Bangumi | None)
async def get_bangumi_by_id(bangumi_id: int, db: Database = Depends(get_db)):
    return await db.bangumi.search_id(bangumi_id)


@router.post("/add", response_model=APIResponse)
async def add_bangumi(data: Bangumi, db: Database = Depends(get_db)):
    await db.bangumi.add(data)
    return JSONResponse(
        status_code=200,
        content={"msg_en": "Add bangumi successfully.", "msg_zh": "添加番剧成功。"},
    )


@router.patch("/update/{bangumi_id}", response_model=APIResponse)
async def update_bangumi(
    bangumi_id: int, data: BangumiUpdate, db: Database = Depends(get_db)
):
    if await db.bangumi.update(bangumi_id, data):
        return JSONResponse(
            status_code=200,
            content={
                "msg_en": "Update bangumi successfully.",
                "msg_zh": "更新番剧成功。",
            },
        )
    return JSONResponse(
        status_code=404,
        content={"msg_en": "Update bangumi failed.", "msg_zh": "更新番剧失败。"},
    )


@router.delete("/delete/{bangumi_id}", response_model=APIResponse)
async def delete_bangumi(bangumi_id: int, db: Database = Depends(get_db)):
    """软删除：置 deleted=True，数据保留。"""
    if await db.bangumi.disable_rule(bangumi_id):
        return JSONResponse(
            status_code=200,
            content={
                "msg_en": "Delete bangumi successfully.",
                "msg_zh": "删除番剧成功。",
            },
        )
    return JSONResponse(
        status_code=404,
        content={"msg_en": "Delete bangumi failed.", "msg_zh": "删除番剧失败。"},
    )
