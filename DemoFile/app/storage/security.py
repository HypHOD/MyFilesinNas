"""路径 / 文件名安全检查。对应 LocalServiceImpl 里的 checkPathSecurity / checkNameSecurity。

Java 里这俩是 LocalServiceImpl 的 private static，搬到独立模块的理由：
  ① pytest 能直接打（这是安全代码，必须单独测）
  ② 以后 FTP / SFTP / S3 实现能复用（它们的路径穿越风险是一样的）

⚠️ 这两段不是"防御性编程"，是**漏洞修复代码**。少判一种形态就是真漏洞，
别简化、别合并、别用 os.path.normpath 之类"顺手"的东西去替代。
"""

from app.core.errors import FilePathSecurityBizException


def check_path_security(*paths: str | None) -> None:
    """检查路径合法性。对应 LocalServiceImpl.checkPathSecurity（Java 298-310 行）。

    规格：
      - None 跳过（有些调用点会传可空参数）
      - '\\' 先统一成 '/'（不能只按 '/' 切 —— Windows 风格的分隔符同样能穿越）
      - 按 '/' **分段**，任意一段等于 '..' 就抛 FilePathSecurityBizException(path)

    必须覆盖的形态：'..'、'/..'、'..\\foo'、'test/..'、'foo/../bar'
    —— 注意 'test/..' 和 'foo/../bar'：如果写成 `if '..' in path` 会**漏掉** 'test/..'
    （不出现在这里但更隐蔽的写法 `path.startswith('..')` 更糟）。
    这就是它必须分段的唯一原因。

    TODO 写实现
    """
    # raise NotImplementedError
    for path in paths:
        if path is None:
            continue
        normalized = path.replace("\\", "/")
        for segment in normalized.split("/"):
            if(segment == ".."):
                raise FilePathSecurityBizException(path)
            


def check_name_security(*names: str | None) -> None:
    """检查文件名合法性。对应 LocalServiceImpl.checkNameSecurity（Java 313-333 行）。

    规格：
      - None 跳过
      - 名字里含 '\\' 或 '/' → 抛异常（否则 'a/b' 这种名字会变成"往子目录里写"）
      - 名字恰好是 '.' 或 '..' → 抛异常（拼上去就指向当前/父级目录）
      - 其它一律放行：'a..b.txt'、'...'、'..a' 都**是合法文件名**，别误杀

    TODO 写实现
    """
    # raise NotImplementedError
    for name in names:
        if name is None:
            continue
        if "\\" in name or "/" in name or name in (".",".."):
            raise FilePathSecurityBizException(name)
        
