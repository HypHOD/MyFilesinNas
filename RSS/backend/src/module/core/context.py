"""应用组合根 构造整个应用的对象图

``AppContext`` 由 ``create_app`` 构造、由 lifespan 拥有其生命周期：持有
settings 与调度器，负责启动建表、后台任务的启停与配置热重载。
"""

import asyncio
import logging
from pathlib import Path

from module.conf import VERSION, settings
from module.database import Database
from module.downloader import DownloadClient
from module.downloader.download_client import _reset_client_cache
from module.downloader.download_client import shutdown as downloader_shutdown
from module.models import Config, ResponseModel
from module.network.request_url import reset_shared_client
from module.rss import RSSAnalyser

from .loops import rename_tick, rss_tick
from .scheduler import PeriodicTask, Scheduler

logger = logging.getLogger(__name__)

# 用户完成初始化引导后写入；存在即不再视为首次运行
SETUP_COMPLETE_PATH = Path("config/.setup_complete")

# 启动时等待下载器就绪的重试节奏：10 次 × 30s ≈ 5 分钟
_DOWNLOADER_MAX_RETRIES = 10
_DOWNLOADER_RETRY_INTERVAL = 30

figlet = r"""
  __  __  _____  _   _ 
 |  \/  ||  ___|| \ | |
 | |\/| || |_   |  \| |
 | |  | ||  _|  | |\  |
 |_|  |_||_|    |_| \_|
                       
"""


class AppContext:
    """应用级上下文，用途编排启动/停止/重载。"""

    def __init__(self, settings_obj, scheduler: Scheduler) -> None:
        self.settings = settings_obj
        self.scheduler = scheduler
        self._startup_done = False
        self._lifecycle_lock = asyncio.Lock()
        # start_tasks() ，stop() 时取消
        self._start_task: asyncio.Task | None = None
        # True 表示本次启动是首次运行（配置全默认）：lifespan 不自动启动循环
        self.first_run_boot = False

    # ------------------------------------------------------------------ build

    @classmethod
    def build(cls, settings_obj) -> "AppContext":
        """纯接线：构造对象图，不做任何 I/O。

        interval / enabled 用 lambda 读 live settings，配置热重载后无需重建；
        analyser 无状态，由闭包常驻复用（与参考实现同构）。
        """
        analyser = RSSAnalyser()
        scheduler = Scheduler(
            [
                PeriodicTask(
                    name="rss",
                    run=lambda: rss_tick(analyser),
                    interval=lambda: settings_obj.program.rss_time,
                    enabled=lambda: settings_obj.rss_parser.enable,
                ),
                PeriodicTask(
                    name="rename",
                    run=rename_tick,
                    interval=lambda: settings_obj.program.rename_time,
                    enabled=lambda: settings_obj.bangumi_manage.enable,
                ),
            ]
        )
        return cls(settings_obj, scheduler)

    # ------------------------------------------------------------------ status

    @property
    def is_running(self) -> bool:
        start_pending = self._start_task is not None and not self._start_task.done()
        return self.scheduler.running or start_pending

    @property
    def first_run(self) -> bool:
        """未写 setup 完成标记、且配置仍是全默认值 → 视为首次运行。"""
        if SETUP_COMPLETE_PATH.exists():
            return False
        return self.settings.model_dump() == Config().model_dump()

    # ------------------------------------------------------------------ startup

    @staticmethod
    def _start_info() -> None:
        for line in figlet.splitlines():
            logger.info(line.strip("\n"))
        logger.info("RSS (Auto_Bangumi 复现)  Version %s", VERSION)
        logger.info("Starting server...")

    async def startup(self) -> None:
        """建表 + 首次运行检测；由 lifespan 在开始服务前 await。

        任何失败都直接中止启动（loud fail），而不是被后台任务吞掉。
        """
        if self._startup_done:
            return
        self._start_info()
        async with Database() as db:
            await db.create_table()
        self.first_run_boot = self.first_run
        self._startup_done = True

    # ------------------------------------------------------------------ tasks
    # 无锁的热更新启动, 立刻返回不阻塞重启
    async def start_tasks(self) -> ResponseModel:
        """拉起「启动循环」后台任务并立即返回（不阻塞 API/lifespan）。"""
        async with self._lifecycle_lock:
            return await self._start_tasks_unlocked()

    async def _start_tasks_unlocked(self) -> ResponseModel:
        # 走统一热重载入口：保证用最新设置启动，且共享客户端与缓存同步刷新
        await self._reload_settings_unlocked()
        if not self.scheduler.running and (
            self._start_task is None or self._start_task.done()
        ):
            self._start_task = asyncio.create_task(self._run_start_tasks())
            self._start_task.add_done_callback(self._supervise_start_task)
        return ResponseModel(
            status=True,
            status_code=200,
            msg_en="Program starting.",
            msg_zh="程序启动中。",
        )

    @staticmethod
    async def _check_downloader() -> tuple[bool, str | None]:
        """下载器可达性检查，附失败原因（unreachable | credentials | banned）。

        mock 恒可用直接放行；``DownloadClient()`` 构造自身可能抛（下载器
        类型无法识别），必须一并纳入处理——否则一个配置错误会击穿启动等待
        循环。凭据错误/封禁的原因由具体客户端的凭据闩锁记录。
        """
        if settings.downloader.type == "mock":
            return True, None
        client = None
        try:
            client = DownloadClient()
            async with client:
                return True, None
        except ConnectionError:
            reason = getattr(client, "last_auth_error", None)
            return False, reason or "unreachable"
        except Exception as e:
            logger.error("Downloader connect failed: %s", e)
            reason = getattr(client, "last_auth_error", None)
            return False, reason or "unreachable"

    async def _wait_for_downloader(self) -> None:
        """等待下载器就绪（10 次 × 30s）；超时 fail-open 放行启动。

        凭据错误 / IP 被封时等待没有意义——继续探测只会累积失败登录、加剧
        qB 的 WebUI IP ban，立即放弃。fail-open 的理由：下载器稍后恢复时
        周期循环自然可用，不能因为下载器不在线就整体拒绝启动。
        """
        retry_count = 0
        while True:
            ok, reason = await self._check_downloader()
            if ok:
                return
            if reason in ("credentials", "banned"):
                logger.error(
                    "Downloader rejected authentication (%s); giving up. "
                    "Program will continue but download functions will not work.",
                    reason,
                )
                return
            retry_count += 1
            logger.warning(
                "Downloader is not running. (attempt %s/%s)",
                retry_count,
                _DOWNLOADER_MAX_RETRIES,
            )
            if retry_count >= _DOWNLOADER_MAX_RETRIES:
                logger.error(
                    "Failed to connect to downloader after maximum retries. "
                    "Please check downloader settings and network/proxy "
                    "configuration. Program will continue but download "
                    "functions will not work."
                )
                return
            await asyncio.sleep(_DOWNLOADER_RETRY_INTERVAL)

    async def _run_start_tasks(self) -> None:
        await self._wait_for_downloader()
        async with self._lifecycle_lock:
            if not self.scheduler.running:
                self.scheduler.start_all()
        logger.info("Program running.")

    @staticmethod
    def _supervise_start_task(task: asyncio.Task) -> None:
        """把后台启动任务的异常记入日志，避免静默丢失。"""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Background start task failed", exc_info=exc)

    async def stop(self) -> ResponseModel:
        """取消待启动任务、停止后台循环，返回操作结果。"""
        async with self._lifecycle_lock:
            return await self._stop_unlocked()

    async def _stop_unlocked(self) -> ResponseModel:
        was_running = self.is_running
        if self._start_task is not None:
            self._start_task.cancel()
            try:
                await self._start_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Background start task failed during shutdown: {e}")
            self._start_task = None
        if self.scheduler.running:
            await self.scheduler.stop_all()
        # 停机即释放共享下载器会话；shutdown 幂等，下次使用时惰性重建
        await downloader_shutdown()
        if was_running:
            return ResponseModel(
                status=True,
                status_code=200,
                msg_en="Program stopped.",
                msg_zh="程序停止成功。",
            )
        return ResponseModel(
            status=False,
            status_code=406,
            msg_en="Program is not running.",
            msg_zh="程序未运行。",
        )

    async def restart(self) -> ResponseModel:
        async with self._lifecycle_lock:
            return await self._restart_unlocked()

    async def _restart_unlocked(self) -> ResponseModel:
        stop_ok = True
        try:
            await self._stop_unlocked()
        except Exception as e:
            logger.warning(f"Error during stop in restart: {e}")
            stop_ok = False
        start_ok = True
        try:
            await self._start_tasks_unlocked()
        except Exception as e:
            logger.error(f"Error during start in restart: {e}")
            start_ok = False
        if start_ok and stop_ok:
            return ResponseModel(
                status=True,
                status_code=200,
                msg_en="Program restarted.",
                msg_zh="程序重启成功。",
            )
        elif start_ok:
            return ResponseModel(
                status=True,
                status_code=200,
                msg_en="Program restarted (stop had warnings).",
                msg_zh="程序重启成功（停止时有警告）。",
            )
        return ResponseModel(
            status=False,
            status_code=500,
            msg_en="Program failed to restart.",
            msg_zh="程序重启失败。",
        )

    # ------------------------------------------------------------------ reload

    async def reload_settings(self) -> None:
        """配置更新的唯一入口：重载配置并热应用（调度器重启）。

        调用方必须走这里而非裸 ``settings.load()``，否则共享 HTTP 客户端、
        下载器实例与调度器会与新配置脱节。
        """
        async with self._lifecycle_lock:
            await self._reload_settings_unlocked()

    async def _reload_settings_unlocked(self) -> None:
        # settings.load() 是同步文件 I/O，放线程池避免阻塞事件循环
        await asyncio.to_thread(settings.load)
        # host/密码可能改了：换掉共享 HTTP 客户端与下载器实例；丢弃下载器
        # 实例同时清掉凭据闩锁——保存设置视为用户已处理凭据问题，允许重试
        await reset_shared_client()
        _reset_client_cache()
        if self.scheduler.running:
            await self.scheduler.stop_all()
            self.scheduler.start_all()
