"""路径与文件名安全检查，对应 LocalServiceImpl.checkPathSecurity / checkNameSecurity。

独立成模块，一是便于 pytest 直接覆盖，二是 FTP / SFTP / S3 等实现可以复用同一套
路径穿越检查。

这些分支是漏洞修复代码，少判一种形态就是真实漏洞。修改时保持分段检查的原始语义，
不要用 normpath 一类会改变判断结果的方式替代。
"""

from app.core.errors import FilePathSecurityBizException


def check_path_security(*paths: str | None) -> None:
    """检查路径中是否包含父目录跳转。对应 LocalServiceImpl.checkPathSecurity。

    None 跳过，因为部分调用点允许可空参数。'\\' 先统一为 '/'（Windows 风格分隔符
    同样可以穿越），再按 '/' 分段，任一段等于 '..' 即抛
    FilePathSecurityBizException(path)。

    必须分段而不是做字符串包含判断：文件名允许出现连续两个点（如 'a..b.txt'），
    只有恰好等于 '..' 的完整路径段才是跳转。startswith('..') 则漏掉 'test/..'
    和 'foo/../bar'。需要覆盖的形态包括 '..'、'/..'、'..\\foo'、'test/..'、
    'foo/../bar'。
    """
    for path in paths:
        if path is None:
            continue
        normalized = path.replace("\\", "/")
        for segment in normalized.split("/"):
            if(segment == ".."):
                raise FilePathSecurityBizException(path)
            


def check_name_security(*names: str | None) -> None:
    """检查文件名合法性。对应 LocalServiceImpl.checkNameSecurity。

    None 跳过。名字中出现 '\\' 或 '/' 时抛异常，否则 'a/b' 会变成向子目录写入；
    名字恰好是 '.' 或 '..' 时抛异常，拼接后会指向当前或父级目录。其余情况一律
    放行：'a..b.txt'、'...'、'..a' 都是合法文件名。
    """
    for name in names:
        if name is None:
            continue
        if "\\" in name or "/" in name or name in (".",".."):
            raise FilePathSecurityBizException(name)
        
