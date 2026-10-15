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

# 全量权限串：19 个操作 value 用逗号连接。
# ★ 给 guest(id=2) 也插一行 —— 否则匿名访问首页什么都看不到。
#   Java 是"新建存储源时按各用户 default_permissions 自动生成授权行"
#   （addDefaultPermissionsForAllUsersInStorageSource），我们没实现那套，所以必须显式插。
# 真实项目别给 guest 全量（至少裁掉 delete / upload）。
FULL_PERMISSIONS = ",".join(op.value for op in FileOperatorType)


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
      ③ storage_source_config：name='filePath'，value=str(DEMO_DIR)，
           title="文件路径", type="local", storage_id=上一步的 id
         （按 (storage_id, name) 查重。）
         ★ 只插 filePath 一行就够：proxyPrivate / proxyTokenTime / proxyLinkForceDownload /
           domain 四个参数靠 Pydantic 默认值兜底。Java 保存时会写全量参数行，这是刻意的差异。
      ④ user_storage_source：user_id 分别 1(管理员) 和 2(guest)，
           root_path="/", enable=True, permissions=FULL_PERMISSIONS
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
        config = db.scalar(
            select(StorageSourceConfig.storage_id).where(
                StorageSourceConfig.storage_id == storage_source.id,
                StorageSourceConfig.name == "filePath",
            )
        )
        if config is None:
            db.add(StorageSourceConfig(
                name="filePath",
                type="local",
                title="文件路径",
                storage_id=storage_source.id,
                value = str(DEMO_DIR),
            ))
        for user_id in (ADMIN_ID, ANONYMOUS_ID):
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
                      root_path="/",
                      enable=True,
                      permissions=FULL_PERMISSIONS,
                  ))
        db.commit()
        print(f"存储源已就绪: id={storage_source.id}, key={STORAGE_KEY}, 目录={DEMO_DIR}")



if __name__ == "__main__":
    main()
