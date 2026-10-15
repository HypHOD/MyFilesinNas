"""步骤 4 验收：本地存储。全部在临时目录里跑 —— **不碰 DB、不启 FastAPI**。
（这正是 _lookup_user_root_path / _get_base_url 两个钩子存在的意义。）

    cd ~/Documents/workbase/DemoFile && python -m pytest tests/ -v

⚠️ 用 `python -m pytest` 而不是裸 `pytest`：tests/ 下没有 __init__.py 时，pytest 只把
tests/ 本身塞进 sys.path，`import app` 会 ModuleNotFoundError。
（要么用 -m，要么在项目根放个空的 conftest.py。）

测试名和断言就是我给的验收清单，你可以自由重命名/重组，但**安全那几条一条都别删**。
"""

from datetime import datetime
from pathlib import Path

import pytest

from app.core.errors import BizException, ErrorCode, FilePathSecurityBizException
from app.storage.enums import FileType, StorageType, UploadType
from app.storage.impl.local import LocalServiceImpl
from app.storage.params import LocalParam


@pytest.fixture
def file_tree(tmp_path: Path) -> Path:
    """造一棵固定的文件树（只读用）。

    {tmp}/storage/             ← param.filePath（存储源根）
    ├── alice/                  ← 用户根（make_service 的 user_root = "/alice"）
    │   ├── sub/
    │   │   ├── a.txt          (5 字节)
    │   │   └── 电影.mp4        (100 字节)
    │   ├── empty/             (空目录)
    │   ├── root.txt           (3 字节)
    │   └── .hidden            (4 字节)
    └── bob/
        └── secret.txt         (4 字节)  ← 验证"看不到别人的文件"
    """
    root = tmp_path / "storage"
    (root / "alice" / "sub").mkdir(parents=True)
    (root / "alice" / "empty").mkdir()
    (root / "bob").mkdir()
    (root / "alice" / "sub" / "a.txt").write_bytes(b"12345")
    (root / "alice" / "sub" / "电影.mp4").write_bytes(b"x" * 100)
    (root / "alice" / "root.txt").write_bytes(b"abc")
    (root / "alice" / ".hidden").write_bytes(b"hide")
    (root / "bob" / "secret.txt").write_bytes(b"bob!")
    return root


def make_service(
    root: Path,
    user_root: str = "/alice",
    base_url: str = "http://127.0.0.1:8080",
) -> LocalServiceImpl:
    """造一个不依赖 DB 的本地存储源实例。五步：

      1. svc = LocalServiceImpl()
      2. svc.init(name=..., storage_id=1, storage_key="local", param=LocalParam(filePath=str(root)))
      3. 覆写 svc._lookup_user_root_path：对任何 user_id 都返回 user_root
      4. 覆写 svc._get_base_url：返回 base_url
      5. 覆写 svc._sign_download_url：步骤 7 才有真实现，先给占位值
         （列表项里每条都带 url，不塞这个占位的话所有列表测试都会红）

    （覆写实例属性就等于 Java 里换掉注入的 Bean，测试里是最省事的做法。）
    """
    svc = LocalServiceImpl()
    svc.init(name="本地", storage_id=1, storage_key="local", param=LocalParam(filePath=str(root)))
    svc._lookup_user_root_path = lambda user_id: user_root
    svc._get_base_url = lambda: base_url
    svc._sign_download_url = lambda path_and_name: "stub-signature"
    return svc


# ─────────────────────────────────────────────────────────────
# 列目录
# ─────────────────────────────────────────────────────────────

def test_folder_size_is_none(file_tree: Path) -> None:
    """文件夹 size 必须是 None（不是 0）—— 前端靠它显示 "-"。"""
    svc = make_service(file_tree)
    items = {i.name: i for i in svc.file_list("/")}

    assert items["sub"].type == FileType.FOLDER
    assert items["sub"].size is None
    assert items["root.txt"].type == FileType.FILE
    assert items["root.txt"].size == 3


def test_file_list_names(file_tree: Path) -> None:
    """file_list("/sub") 返回 {a.txt, 电影.mp4}（中文名不许乱码）。"""
    assert {i.name for i in make_service(file_tree).file_list("/sub")} == {"a.txt", "电影.mp4"}


def test_file_list_empty_folder(file_tree: Path) -> None:
    """空目录返回 []，不抛异常。"""
    assert make_service(file_tree).file_list("/empty") == []


def test_path_is_parent_folder(file_tree: Path) -> None:
    """item.path 是**父目录**：根目录下的项 path == "/"，sub 里的项 path == "/sub"。"""
    assert {i.path for i in make_service(file_tree).file_list("/")} == {"/"}
    assert {i.path for i in make_service(file_tree).file_list("/sub")} == {"/sub"}


def test_file_item_fields(file_tree: Path) -> None:
    """a.txt 的 name / type / size / time（time 是 datetime，且和文件 mtime 一致）。"""
    item = make_service(file_tree).get_file_item("/sub/a.txt")

    assert item.name == "a.txt"
    assert item.type == FileType.FILE
    assert item.size == 5
    assert isinstance(item.time, datetime)
    assert item.time == datetime.fromtimestamp(
        (file_tree / "alice" / "sub" / "a.txt").stat().st_mtime
    )


def test_folder_has_no_url(file_tree: Path) -> None:
    """文件夹的 url 是 None（只有文件才给下载地址）。"""
    items = {i.name: i for i in make_service(file_tree).file_list("/")}

    assert items["sub"].url is None
    assert items["root.txt"].url is not None


# ─────────────────────────────────────────────────────────────
# ★ 路径契约
# ─────────────────────────────────────────────────────────────

def test_file_url_contains_user_root(file_tree: Path) -> None:
    """/sub/a.txt 的 url 里必须出现 "/alice/sub/a.txt"（证明 _to_file_item 拼了用户根）。"""
    items = {i.name: i for i in make_service(file_tree).file_list("/")}

    assert "/alice/root.txt" in items["root.txt"].url


def test_download_url_does_not_double_user_root(file_tree: Path) -> None:
    """get_download_url("/alice/sub/a.txt") 的结果里 "/alice" 只出现 **一次**。

    这是步骤 7 埋的雷：入参已经是绝对路径，实现里再拼一次用户根就会变成
    /alice/alice/sub/a.txt（Java 仓库 469b9d4 修的就是这个）。
    """
    url = make_service(file_tree).get_download_url("/alice/sub/a.txt")

    assert url.count("/alice") == 1
    assert "/alice/alice" not in url


def test_download_url_shape(file_tree: Path) -> None:
    """未配 param.domain 时走代理：http://127.0.0.1:8080/pd/local/... （签名步骤 7 再补）。"""
    url = make_service(file_tree).get_download_url("/alice/sub/a.txt")

    assert url.startswith("http://127.0.0.1:8080/pd/local/alice/sub/a.txt")
    assert "signature=" in url


def test_other_user_root_hides_files(file_tree: Path) -> None:
    """user_root="/bob" 时只看得到 secret.txt，看不到 alice 下的任何东西。"""
    svc = make_service(file_tree, user_root="/bob")

    assert {i.name for i in svc.file_list("/")} == {"secret.txt"}
    # bob 的根下没有 sub/ —— 拼的是 /bob/sub，不是 /alice/sub
    with pytest.raises(BizException):
        svc.file_list("/sub")


# ─────────────────────────────────────────────────────────────
# 单文件 / 校验
# ─────────────────────────────────────────────────────────────

def test_get_file_item_missing_returns_none(file_tree: Path) -> None:
    """不存在的文件返回 None，不抛异常。"""
    assert make_service(file_tree).get_file_item("/nope.txt") is None


def test_get_file_item_path_is_parent(file_tree: Path) -> None:
    """get_file_item("/sub/a.txt").path == "/sub"（不是 "/sub/a.txt"）。"""
    assert make_service(file_tree).get_file_item("/sub/a.txt").path == "/sub"


def test_init_rejects_missing_file_path(tmp_path: Path) -> None:
    """filePath 目录不存在时 init 该抛 BizException，且错误码是 43011。"""
    svc = LocalServiceImpl()
    with pytest.raises(BizException) as ei:
        svc.init(name="x", storage_id=1, storage_key="k",
                 param=LocalParam(filePath=str(tmp_path / "nope")))

    assert ei.value.error_code == ErrorCode.BIZ_STORAGE_INIT_ERROR
    assert ei.value.error_code.code == "43011"


def test_double_init_rejected(file_tree: Path) -> None:
    """同一个实例 init 两次 → IllegalStateException（对应 Java 的"请勿重复初始化"）。"""
    svc = make_service(file_tree)

    with pytest.raises(RuntimeError):
        svc.init(name="本地", storage_id=1, storage_key="local",
                 param=LocalParam(filePath=str(file_tree)))


def test_test_connection_sets_initialized(file_tree: Path) -> None:
    """test_connection() 之后 is_initialized 为 True。

    （这一步会走 get_current_user_base_path 的"未初始化 → 强制管理员 id"分支，
    而 _lookup_user_root_path 被测试覆写成忽略 user_id，所以照样能列出文件。）
    """
    svc = make_service(file_tree)

    assert svc.is_initialized is False
    svc.test_connection()
    assert svc.is_initialized is True


# ─────────────────────────────────────────────────────────────
# 文件操作
# ─────────────────────────────────────────────────────────────

def test_new_folder(file_tree: Path) -> None:
    """new_folder("/", "new") 之后能在列表里看到 new/。"""
    svc = make_service(file_tree)

    assert svc.new_folder("/", "new") is True
    assert (file_tree / "alice" / "new").is_dir()


def test_new_folder_creates_parent_dirs(file_tree: Path) -> None:
    """new_folder("/sub/deep/deeper", "x") 能递归建出多层（Java 用 hutool mkdir 的语义）。"""
    svc = make_service(file_tree)

    assert svc.new_folder("/sub/deep/deeper", "x") is True
    assert (file_tree / "alice" / "sub" / "deep" / "deeper" / "x").is_dir()


def test_delete_not_empty_folder(file_tree: Path) -> None:
    """delete_folder("/", "sub") 要能删掉**非空**目录（sub 里有两个文件）。"""
    svc = make_service(file_tree)

    assert svc.delete_folder("/", "sub") is True
    assert not (file_tree / "alice" / "sub").exists()


def test_rename_file(file_tree: Path) -> None:
    """rename_file("/sub", "a.txt", "b.txt")：旧名消失、新名出现、内容不变。"""
    svc = make_service(file_tree)

    assert svc.rename_file("/sub", "a.txt", "b.txt") is True
    assert (file_tree / "alice" / "sub" / "b.txt").read_bytes() == b"12345"
    assert not (file_tree / "alice" / "sub" / "a.txt").exists()


def test_copy_ignores_target_name(file_tree: Path) -> None:
    """COPY 时 target_name 是**被忽略**的（Java 的 appendName 逻辑）：

    copy_file("/sub", "a.txt", "/", "随便什么名") → 结果是 "/a.txt"，不是 "/随便什么名"。
    """
    svc = make_service(file_tree)

    svc.copy_file("/sub", "a.txt", "/", "随便什么名")
    assert (file_tree / "alice" / "a.txt").read_bytes() == b"12345"   # 原名活着
    assert not (file_tree / "alice" / "随便什么名").exists()            # target_name 被忽略
    assert (file_tree / "alice" / "sub" / "a.txt").exists()           # 源文件还在


def test_move_file(file_tree: Path) -> None:
    """move_file("/sub", "a.txt", "/empty", "moved.txt") → /empty/moved.txt 存在，原位置没了。"""
    svc = make_service(file_tree)

    assert svc.move_file("/sub", "a.txt", "/empty", "moved.txt") is True
    assert (file_tree / "alice" / "empty" / "moved.txt").exists()
    assert not (file_tree / "alice" / "sub" / "a.txt").exists()


def test_operate_same_name_is_noop(file_tree: Path) -> None:
    """改名成自己（path/name 都没变）→ 返回 True 且文件还在。"""
    svc = make_service(file_tree)

    assert svc.rename_file("/sub", "a.txt", "a.txt") is True
    assert (file_tree / "alice" / "sub" / "a.txt").exists()


# ─────────────────────────────────────────────────────────────
# ★ 安全：这些一条都不能少
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_path", ["/..", "/sub/..", "/sub/../..", "..\\sub", "/..\\.."])
def test_rejects_parent_traversal(file_tree: Path, bad_path: str) -> None:
    """所有 ../ 形态都必须抛 FilePathSecurityBizException。

    注意 "/sub/.." 这条：写成 `if ".." in path` 反而能过，写成 `path.startswith("..")`
    就漏了 —— 这就是必须按 "/" 和 "\\" **分段**判断的原因。
    """
    with pytest.raises(FilePathSecurityBizException):
        make_service(file_tree).file_list(bad_path)


@pytest.mark.parametrize("bad_name", ["..", ".", "a/b", "a\\b"])
def test_new_folder_rejects_bad_name(file_tree: Path, bad_name: str) -> None:
    """文件名是 .. / . / 含斜杠 → 抛异常（否则会写到别的目录去）。"""
    with pytest.raises(FilePathSecurityBizException):
        make_service(file_tree).new_folder("/", bad_name)


def test_rename_rejects_bad_new_name(file_tree: Path) -> None:
    """rename_file("/", "root.txt", "../escaped.txt") 必须被拦。"""
    svc = make_service(file_tree)

    with pytest.raises(FilePathSecurityBizException):
        svc.rename_file("/", "root.txt", "../escaped.txt")

    assert (file_tree / "alice" / "root.txt").exists()


def test_legal_names_are_not_rejected(file_tree: Path) -> None:
    """别误杀：new_folder("/", "a..b") 和 new_folder("/", "...") 都应该成功。"""
    svc = make_service(file_tree)

    assert svc.new_folder("/", "a..b") is True
    assert svc.new_folder("/", "...") is True


# ─────────────────────────────────────────────────────────────
# 元数据
# ─────────────────────────────────────────────────────────────

def test_storage_type_and_metadata(file_tree: Path) -> None:
    """get_storage_type() == StorageType.LOCAL；
    metadata.uploadType == UploadType.PROXY，needCreateFolderBeforeUpload is False，
    其余 4 个 bool 保持默认 True。
    """
    svc = make_service(file_tree)
    md = svc.get_storage_source_metadata()

    assert svc.get_storage_type() == StorageType.LOCAL
    assert md.uploadType == UploadType.PROXY
    assert md.needCreateFolderBeforeUpload is False
    assert md.supportRenameFolder and md.supportMoveFolder
    assert md.supportCopyFolder and md.supportDeleteNotEmptyFolder
