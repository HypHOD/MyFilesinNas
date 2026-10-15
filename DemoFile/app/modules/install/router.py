from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.response import AjaxJson, success, success_data
from app.modules.install.schemas import InstallSystemRequest
from app.modules.install.service import get_system_is_installed, install

router = APIRouter(prefix="/install", tags=["install"])


@router.get("/status")
def is_install(db: Session = Depends(get_db)) -> AjaxJson[bool]:
    return success_data(get_system_is_installed(db))


@router.post("")
def do_install(request: InstallSystemRequest, db: Session = Depends(get_db)) -> AjaxJson:
    install(db, request)
    return success()
