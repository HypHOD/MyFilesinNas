from enum import Enum

class ErrorCode(Enum):
    SYSTEM_ERROR = ("50000", "系统异常")
    INVALID_STORAGE_SOURCE = ("50001", "无效或初始化失败的存储源")
    BIZ_SYSTEM_ALREADY_INIT = ("40001", "系统已初始化，请勿重复初始化")
    BIZ_NOT_FOUND = ("40400", "NOT FOUND")
    BIZ_BAD_REQUEST = ("41000","请求参数异常")
    BIZ_UNSUPPORTED_PROXY_DOWNLOAD = ("41001", "该存储源不支持代理下载")
    BIZ_INVALID_SIGNATURE = ("41002", "签名无效或下载地址已过期")
    BIZ_FILE_NOT_EXIST = ("41004", "文件不存在")
    BIZ_FILE_PATH_ILLEGAL = ("41009", "文件名/路径存在安全隐患")
    BIZ_STORAGE_NOT_FOUND = ("41017", "存储源不存在")
    BIZ_INVALID_FILE_NAME = ("41022", "文件名不合法")
    BIZ_FOLDER_NOT_EXIST = ("41026", "文件夹不存在")
    BIZ_UNAUTHORIZED = ("42000", "未登录或未授权")
    BIZ_LOGIN_ERROR = ("42001", "登录失败, 账号或密码错误")
    BIZ_STORAGE_INIT_ERROR = ("43011", "存储源初始化失败")
    NO_FORBIDDEN = ("30000", "没有权限")

    def __init__(self, code: str, msg: str) -> None:
        self.code = code
        self.msg = msg

class BizException(Exception):
    """业务异常。HTTP 状态码默认 500，由全局异常处理器转换为响应信封。"""
    http_status = 500
    def __init__(self, error_code: ErrorCode, msg: str | None = None) -> None:
        self.error_code = error_code
        self.msg = msg if msg is not None else error_code.msg
        super().__init__(self.msg)

class UnauthorizedAccessException(BizException):
    http_status = 401

    def __init__(self, msg: str = "未登录，请登录后再次访问") -> None:
        super().__init__(ErrorCode.BIZ_UNAUTHORIZED, msg)


class FilePathSecurityBizException(BizException):
    """对应 Java FilePathSecurityBizException：路径包含 ../ 等穿越企图。

    单独成类是为了携带非法路径，便于全局处理器记录 warning。这类日志是入侵探测
    信号，不应与普通的"文件不存在"混在一起。异常处理器无需特殊处理，
    BizException 的通用分支会接住。
    """

    def __init__(self, path: str) -> None:
        super().__init__(ErrorCode.BIZ_FILE_PATH_ILLEGAL)
        self.path = path