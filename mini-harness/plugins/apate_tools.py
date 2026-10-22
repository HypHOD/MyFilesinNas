'''对文件进行apate隐写
    伪装逻辑 [伪装mask][原文件内容][逆序的原文件N字节][int32 小端mask长度]
    N = min(mask长度, 原文件长度)
'''

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Iterable, Optional, Tuple, Union

PathLike = Union[str, os.PathLike]

MAX_MASK_LENGTH = 2_147_483_647 // 7
FOOTER_SIZE = 4
_LENGTH_FORMAT = "<i"

# mask载体校验
JPG_HEAD = bytes.fromhex("ffd8ffe1")
MOV_HEAD = bytes.fromhex("6d6f6f76")
MP4_HEAD = bytes.fromhex(
    "000000206674797069736f6d0000020069736f6d69736f32617663316d703431"
)
EXE_HEAD = bytes.fromhex(
    "4d5a90000300000004"
    "000000ffff0000b80000000000000040"
    "00000000000000000000000000000000"
    "00000000000000000000000000000000"
    "000000800000000e1fba0e00b409cd21"
    "b8014ccd21546869732070726f677261"
    "6d2063616e6e6f742062652072756e20"
    "696e20444f53206d6f64652e0d0d0a24"
    "00000000000000"
)

SIMPLE_MODES = {
    "exe": (EXE_HEAD, ".exe"),
    "jpg": (JPG_HEAD, ".jpg"),
    "mp4": (MP4_HEAD, ".mp4"),
    "mov": (MOV_HEAD, ".mov"),
}

ONE_KEY_EXTENSION = ".mp4"

MODES = ("onekey", "mask", *SIMPLE_MODES)

class ApateError(Exception):
    '''伪装失败'''

def disguise(path: PathLike,mask: bytes)->None:
    '''就地伪装文件'''
    if not mask:
        raise ApateError("mask为空")
    with open(path,"r+b") as file:
        size = os.fstat(file.fileno()).st_size
        head = file.read(min(len(mask),size))
        file.seek(0)
        file.write(mask)
        file.seek(0,os.SEEK_END)
        file.write(head[::-1])
        file.write(struct.pack(_LENGTH_FORMAT,len(mask)))

def reveal(path: PathLike) -> int:
    '''还原被伪装文件 返回文件中记录面具的长度 未伪装文件使用会损坏数据'''
    with open(path, "r+b") as file:
        size = os.fstat(file.fileno()).st_size
        if size < FOOTER_SIZE:
            raise ApateError("文件太小，不是伪装文件")

        file.seek(size - FOOTER_SIZE)
        footer = file.read(FOOTER_SIZE)
        (mask_length,) = struct.unpack(_LENGTH_FORMAT, footer)
        available = size - FOOTER_SIZE - mask_length
        if mask_length <= 0 or available < 0:
            raise ApateError("文件末尾没有有效的面具长度标记，可能不是伪装文件")

        if mask_length <= available:
            offset, head_length = available, mask_length
        else:
            offset, head_length = mask_length, available

        file.seek(offset)
        head = file.read(head_length)
        if len(head) != head_length:
            raise ApateError("读取原始文件头失败")

        file.truncate(available)
        file.seek(0)
        file.write(head[::-1])
        return mask_length

def collect_files(targets: Iterable[PathLike]) -> list[Path]:
    '''展开并收集路径下全部文件'''
    files: list[Path] = []
    for target in targets:
        path = Path(target)
        if path.is_dir():
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames.sort()
                filenames.sort()
                files.extend(Path(dirpath) / name for name in filenames)
        elif path.is_file():
            files.append(path)
        else:
            raise ApateError(f"路径不存在: {path}")
        return files

def disguised_name(path: Path, extension: str) -> Path:
    """伪装后的文件名：直接在原名后追加面具扩展名（如 a.zip -> a.zip.mp4）。"""
    return path.with_name(path.name + extension)

def revealed_name(path: Path) -> Path:
    """还原后的文件名：去掉最后一个扩展名；没有扩展名则保持原名。"""
    if not path.suffix:
        return path
    return path.with_name(path.name[: -len(path.suffix)])

def load_mask_file(path: PathLike) -> bytes:
    """读取面具文件，限制大小与 C# 版一致（0 < size < MAX_MASK_LENGTH）。"""
    mask_path = Path(path)
    if mask_path.is_dir():
        raise ApateError(f"面具不能是文件夹: {mask_path}")
    size = mask_path.stat().st_size
    if size <= 0:
        raise ApateError(f"面具文件为空: {mask_path}")
    if size >= MAX_MASK_LENGTH:
        limit_mb = MAX_MASK_LENGTH // 1024 // 1024
        raise ApateError(f"面具文件过大，请更换小于 {limit_mb}MB 的文件: {mask_path}")
    return mask_path.read_bytes()


def one_key_mask_path() -> Path:
    '''指定mask'''
    return Path(__file__).resolve().parent / "src" / "mask.mp4"

def mask_for_mode(
    mode: str, mask_path: Optional[PathLike] = None
) -> Tuple[bytes, str]:
    """按模式返回 (面具字节, 伪装时追加的扩展名)。"""
    if mode == "onekey":
        return load_mask_file(one_key_mask_path()), ONE_KEY_EXTENSION
    if mode == "mask":
        if mask_path is None:
            raise ApateError("面具伪装需要通过 --mask 指定面具文件")
        path = Path(mask_path)
        if path.is_dir():
            raise ApateError(f"面具不能是文件夹: {path}")
        return load_mask_file(path), path.suffix
    if mode in SIMPLE_MODES:
        return SIMPLE_MODES[mode]
    raise ApateError(f"未知模式: {mode}")


