"""塞一个可用的"本地存储"存储源 + 管理员/匿名两类授权行。

用法：
    cd ~/Documents/workbase/DemoFile && source .venv/bin/activate
    python scripts/init_db.py              # 先建表（storage 三张表由它建）
    python scripts/seed_local_storage.py   # 再灌数据

为什么是脚本不是接口：创建存储源的正规入口是 /admin/storage 那套后台接口，
实现完整后台是独立工程。脚本直接插 DB，效果等价。可以重复执行（幂等）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.storage import StorageSource, StorageSourceConfig, UserStorageSource
from app.storage.enums import FileOperatorType
from app.models.user import ADMIN_ID,ANONYMOUS_ID

# 演示用的真实目录。storage_source_config.filePath 必须指向它（绝对路径）。
DEMO_DIR = Path(__file__).resolve().parent.parent / "demo-storage"

STORAGE_KEY = "local"

# 授权行必须显式插 —— 否则匿名访问首页什么都看不到。
# （Java 是"新建存储源时按各用户 default_permissions 自动生成授权行"
#   addDefaultPermissionsForAllUsersInStorageSource，我们没实现那套。）

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
    """建 DEMO_DIR 和几个演示文件（已存在就跳过）。"""
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
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
    """用途：这个脚本的执行主体 —— 幂等三步：建演示目录 → 保证存储源 + filePath 配置存在 →
    保证 admin/guest 两条授权行存在。跑完接上后端就能验收 /api/storage/list。

    三步，全程幂等（存在即跳过）：

      ① ensure_demo_dir()
      ② storage_source：按 key='local' 查，没有才插。字段值：
           enable=True, name="本地存储", key=STORAGE_KEY, type="local",
           search_enable=True, order_num=0, default_switch_to_img_mode=False,
           enable_cache=False, auto_refresh_cache=False, compatibility_readme=False
      ③ storage_source_config：两行 —— filePath=str(DEMO_DIR) 和
           proxyLinkForceDownload="false"（在线播放必需，理由见下方参数行的注释）；
           其余参数（proxyPrivate / proxyTokenTime / domain）靠 Pydantic 默认值兜底。
         （按 (storage_id, name) 查重。）
      ④ user_storage_source：user_id 分别 1(管理员) 和 2(guest)，enable=True；
           管理员 root_path="/" + FULL_PERMISSIONS（全量），
           游客 root_path=GUEST_ROOT_PATH（公开白名单 /Bangumi）+ READONLY_PERMISSIONS（只读）
         （按 (user_id, storage_source_id) 查重。）

      最后 print 出存储源 id 和 demo 目录路径。

    TODO 写实现
    """
    # return
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
