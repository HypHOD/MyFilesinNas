from pydantic import BaseModel, Field


class Program(BaseModel):
    """调度与 WebUI 设置。
    rss_time
    rename_time
    webui_port
    """

    rss_time: int = Field(default=900, description="RSS 刷新间隔（秒）")
    rename_time: int = Field(default=60, description="重命名轮询间隔（秒）")
    webui_port: int = Field(default=7892, description="WebUI 端口")


class Downloader(BaseModel):
    """下载器连接设置。
    type
    host
    username
    password
    path
    ssl
    """

    type: str = Field(default="qbittorrent", description="下载器类型")
    host: str = Field(default="172.17.0.1:8080", description="下载器地址")
    username: str = Field(default="admin", description="下载器用户名")
    password: str = Field(default="adminadmin", description="下载器密码")
    path: str = Field(default="/downloads/Bangumi", description="下载保存路径")
    ssl: bool = Field(default=False, description="是否使用 https")


class RSSParser(BaseModel):
    """RSS 解析设置。
    enable
    filter: 要增加可选的内容
    language
    """

    enable: bool = Field(default=True, description="启用 RSS 解析")
    filter: list[str] = Field(default=["720", r"\d+-\d+"], description="标题排除规则")
    language: str = Field(default="zh", description="首选标题语言")


class BangumiManage(BaseModel):
    """文件整理与重命名设置。
    enable
    eps_complete
    rename_method
    group_tag
    """

    enable: bool = Field(default=True, description="启用重命名")
    eps_complete: bool = Field(default=False, description="补全遗漏剧集")
    rename_method: str = Field(default="pn", description="重命名方式")
    group_tag: bool = Field(default=False, description="文件名包含字幕组")


class Log(BaseModel):
    """日志设置。
    debug_enable
    """

    debug_enable: bool = Field(default=False, description="启用 DEBUG 日志")


class Config(BaseModel):
    """根配置模型：由各分节组合而成。
    program: 主程序
    downloader: 下载器
    rss_parser: RSS解析器
    bangumi_manager: 番剧管理
    log
    """

    program: Program = Program()
    downloader: Downloader = Downloader()
    rss_parser: RSSParser = RSSParser()
    bangumi_manage: BangumiManage = BangumiManage()
    log: Log = Log()
