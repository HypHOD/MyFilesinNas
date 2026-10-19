"""塞一个可用的"本地存储"存储源 + 管理员/匿名两类授权行。

用法：
    cd ~/Documents/workbase/DemoFile && source .venv/bin/activate
    python scripts/init_db.py              # 先建表（storage 三张表由它建）
    python scripts/seed_local_storage.py   # 再灌数据

为什么是脚本不是接口：创建存储源的正规入口是 /admin/storage 那套后台接口，
实现完整后台是独立工程。脚本直接插 DB，效果等价。可以重复执行（幂等）。

容器/生产部署通过 MFN_STORAGE_PATH 指定存储目录（例如 /media），
此时不会生成演示文件，只确保游客白名单目录存在。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.storage import StorageSource, StorageSourceConfig, UserStorageSource
from app.storage.enums import FileOperatorType
from app.models.user import ADMIN_ID,ANONYMOUS_ID

# storage_source_config.filePath 必须指向真实绝对路径。
# 本地开发默认 demo-storage；容器部署用 MFN_STORAGE_PATH=/media 指向挂载点。
_DEFAULT_DEMO_DIR = Path(__file__).resolve().parent.parent / "demo-storage"
DEMO_DIR = Path(os.environ.get("MFN_STORAGE_PATH", str(_DEFAULT_DEMO_DIR)))
_PRODUCTION_STORAGE = "MFN_STORAGE_PATH" in os.environ

STORAGE_KEY = "local"

# 授权行必须显式插入，否则匿名访问首页看不到任何存储源。
# Java 在新建存储源时会按各用户 default_permissions 自动生成授权行
# （addDefaultPermissionsForAllUsersInStorageSource），这里未实现该逻辑。

# 全量权限串：19 个操作 value 用逗号连接。管理员（id=1）用。
FULL_PERMISSIONS = ",".join(op.value for op in FileOperatorType)

# 游客（guest, id=2）只读权限：available=存储源可用，preview=点击播放。
# 责任链末端 file_download_permission 规定有 DOWNLOAD 或 PREVIEW 才下发签名 url，
# 给 preview 即保证"能看"；不给 download 即"不能下"（前端下载按钮自动隐藏）。
# 其余 17 项（写操作/分享/ignorePassword/ignoreHidden）一律拒绝。
READONLY_PERMISSIONS = ",".join(
    [FileOperatorType.AVAILABLE.value, FileOperatorType.PREVIEW.value]
)

# 游客可见根目录（公开白名单）：只公开 demo-storage 下的番剧库子目录，不是整个网盘。
GUEST_ROOT_PATH = "/Bangumi"


def ensure_demo_dir() -> None:
    """准备存储目录。MFN_STORAGE_PATH 模式只建目录，不生成演示文件。"""
    DEMO_DIR.mkdir(parents=True, exist_ok=True)

    if _PRODUCTION_STORAGE:
        (DEMO_DIR / GUEST_ROOT_PATH.lstrip("/")).mkdir(parents=True, exist_ok=True)
        return

    samples = {
        "说明.txt": "这是本地存储的演示目录，由 scripts/seed_local_storage.py 创建。\n",
        "文档/中文名文件.txt": "用来验证 URL 编码和中文显示。\n",
        "电影/示例.txt": "假装这是一部电影。\n",
    }
    for rel, text in samples.items():
        path = DEMO_DIR / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(text, encoding="utf-8")


def main() -> None:
    """脚本入口：幂等准备本地存储的演示数据。

    依次确保演示目录存在、key='local' 的存储源及其 filePath /
    proxyLinkForceDownload 配置存在、admin 与 guest 两条授权行存在。全部按唯一键
    查重，重复执行不会产生重复数据。

    admin 使用 root_path="/" 与全量权限；guest 使用 GUEST_ROOT_PATH（公开白名单
    /Bangumi）与只读权限。执行完成会打印存储源 id 和演示目录路径。
    """
    ensure_demo_dir()
    with SessionLocal() as db:
        storage_source = db.scalar(select(StorageSource).where(StorageSource.key == STORAGE_KEY))
        if storage_source is None:
             storage_source = StorageSource(
                  enable=True,
                  enable_cache=False,
                  name="本地存储",
                  auto_refresh_cache=False,
                  type=STORAGE_KEY,
                  search_enable=True,
                  order_num=0,
                  default_switch_to_img_mode=False,
                  key=STORAGE_KEY,
                  compatibility_readme=False,
              )
             db.add(storage_source)
             db.flush()
        # 参数行。filePath 必填；proxyLinkForceDownload=false 是"在线播放"的关键：
        # 默认 true 时 /pd/ 把一切文件标成 octet-stream + attachment，浏览器
        # <video>/<audio> 会拒绝加载（媒体元素严格校验 MIME），播放必挂。
        # 设 false 后按真实 MIME 返回（video/mp4 → inline），Range 流照常。
        param_rows = [
            ("filePath", "文件路径", str(DEMO_DIR)),
            ("proxyLinkForceDownload", "代理链接强制下载", "false"),
        ]
        for name, title, value in param_rows:
            exists = db.scalar(
                select(StorageSourceConfig.id).where(
                    StorageSourceConfig.storage_id == storage_source.id,
                    StorageSourceConfig.name == name,
                )
            )
            if exists is None:
                db.add(StorageSourceConfig(
                    name=name,
                    type="local",
                    title=title,
                    storage_id=storage_source.id,
                    value=value,
                ))
        # 授权行：(user_id, root_path, permissions)
        # admin 全量看整库；guest 只读看番剧库白名单。
        grants = [
            (ADMIN_ID, "/", FULL_PERMISSIONS),
            (ANONYMOUS_ID, GUEST_ROOT_PATH, READONLY_PERMISSIONS),
        ]
        for user_id, root_path, permissions in grants:
            uss = db.scalar(
                select(UserStorageSource).where(
                    UserStorageSource.user_id == user_id,
                    UserStorageSource.storage_source_id == storage_source.id,
                )
            )
            if uss is None:
                db.add(UserStorageSource(
                    user_id=user_id,
                    storage_source_id=storage_source.id,
                    root_path=root_path,
                    enable=True,
                    permissions=permissions,
                ))
        db.commit()
        print(f"存储源已就绪: id={storage_source.id}, key={STORAGE_KEY}, 目录={DEMO_DIR}")



if __name__ == "__main__":
    main()
