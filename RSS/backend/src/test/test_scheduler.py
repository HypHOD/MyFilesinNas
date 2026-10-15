import asyncio

from module.core import PeriodicTask, Scheduler


async def test_periodic_task_runs_and_stops():
    calls = []

    async def tick():
        calls.append(1)

    task = PeriodicTask(name="t", run=tick, interval=lambda: 0.05)
    scheduler = Scheduler([task])
    scheduler.start_all()
    assert scheduler.running

    await asyncio.sleep(0.18)
    await scheduler.stop_all()
    assert not scheduler.running
    assert len(calls) >= 2


async def test_tick_exception_does_not_kill_loop():
    calls = []

    async def bad_tick():
        calls.append(1)
        raise RuntimeError("boom")

    task = PeriodicTask(name="bad", run=bad_tick, interval=lambda: 0.05)
    task.start()
    await asyncio.sleep(0.18)
    await task.stop()
    # 异常被吞掉记录，循环持续运行
    assert len(calls) >= 2


async def test_disabled_task_not_started():
    async def tick():
        raise AssertionError("disabled task should not run")

    task = PeriodicTask(
        name="off", run=tick, interval=lambda: 500, enabled=lambda: False
    )
    scheduler = Scheduler([task])
    scheduler.start_all()
    assert not task.running
    await scheduler.stop_all()
