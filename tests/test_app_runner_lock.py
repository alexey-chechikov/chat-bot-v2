"""Один app_runner на учётку: вторая копия не стартует, пока жива первая (flock в main(), 21.10.2026).

Ни один тест здесь не запускает настоящий набор задач: _main_locked подменяется.
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time

import app_runner

HOLDER = ("import fcntl, os, sys, time\n"
          "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)\n"
          "fcntl.flock(fd, fcntl.LOCK_EX)\n"
          "print('locked', flush=True)\n"
          "time.sleep(float(sys.argv[2]))\n")


def _holder(path: str, hold_sec: float) -> subprocess.Popen:
    p = subprocess.Popen([sys.executable, "-c", HOLDER, path, str(hold_sec)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "locked"
    return p


def _fake_body(monkeypatch, result=0):
    ran = []

    async def body(**kw):
        ran.append(kw)
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(app_runner, "_main_locked", body)
    return ran


def _main(path: str, wait: float) -> int:
    return asyncio.run(app_runner.main(signal_handler_installer=lambda loop, ev: None, lock_path=path,
                                       lock_wait_sec=wait))


def test_second_copy_refused_while_first_alive(tmp_path, monkeypatch):
    path = str(tmp_path / "x" / "app_runner.lock")
    ran = _fake_body(monkeypatch, 7)
    first = app_runner._acquire_single_instance_lock(path, wait_sec=0)
    assert first is not None
    try:
        assert open(path).read().strip() == str(os.getpid())
        assert _main(path, 0.3) == app_runner.LOCK_BUSY_EXIT
        assert ran == []                          # набор задач не запускался
    finally:
        os.close(first)
    assert _main(path, 0) == 7 and len(ran) == 1


def test_other_process_holding_lock_blocks_start(tmp_path, monkeypatch):
    path = str(tmp_path / "app_runner.lock")
    ran = _fake_body(monkeypatch)
    p = _holder(path, 30)
    try:
        assert _main(path, 0.3) == app_runner.LOCK_BUSY_EXIT
        assert ran == []
    finally:
        p.kill()
        p.wait()


def test_waits_for_old_process_to_exit_kickstart(tmp_path, monkeypatch):
    path = str(tmp_path / "app_runner.lock")
    ran = _fake_body(monkeypatch)
    p = _holder(path, 1.0)
    t0 = time.monotonic()
    try:
        assert _main(path, 15) == 0 and len(ran) == 1
    finally:
        p.wait()
    assert time.monotonic() - t0 >= 0.5


def test_sigkilled_holder_leaves_no_stale_lock(tmp_path):
    path = str(tmp_path / "app_runner.lock")
    p = _holder(path, 60)
    os.kill(p.pid, signal.SIGKILL)
    p.wait()
    fd = app_runner._acquire_single_instance_lock(path, wait_sec=2)
    assert fd is not None
    os.close(fd)


def test_child_process_does_not_inherit_lock(tmp_path):
    path = str(tmp_path / "app_runner.lock")
    fd = app_runner._acquire_single_instance_lock(path, wait_sec=0)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], close_fds=False)
    try:
        os.close(fd)                              # родитель «умер», потомок жив
        fd2 = app_runner._acquire_single_instance_lock(path, wait_sec=1)
        assert fd2 is not None
        os.close(fd2)
    finally:
        child.kill()
        child.wait()


def test_lock_released_when_body_raises(tmp_path, monkeypatch):
    path = str(tmp_path / "app_runner.lock")
    _fake_body(monkeypatch, KeyboardInterrupt())
    try:
        _main(path, 0)
    except KeyboardInterrupt:
        pass
    fd = app_runner._acquire_single_instance_lock(path, wait_sec=0)
    assert fd is not None
    os.close(fd)


def test_lock_path_does_not_depend_on_cwd_or_checkout():
    assert os.path.isabs(app_runner.LOCK_PATH)
    assert app_runner.LOCK_PATH == os.path.join(os.path.expanduser("~"), ".bot7", "app_runner.lock")


def test_main_defaults_to_shared_lock():
    import inspect
    kw = inspect.signature(app_runner.main).parameters
    assert kw["lock_path"].default == app_runner.LOCK_PATH
    assert kw["lock_wait_sec"].default == app_runner.LOCK_WAIT_SEC


def _blocked_worker_body(monkeypatch):
    """Как проход сеток: asyncio.to_thread(tick); остановка отменяет задачу по таймауту (_shutdown_task), а поток жив."""
    import threading
    ev = {"release": threading.Event(), "started": threading.Event(), "body_done": threading.Event()}

    def worker():
        ev["started"].set()
        ev["release"].wait(10)

    async def body(**kw):
        t = asyncio.ensure_future(asyncio.to_thread(worker))
        while not ev["started"].is_set():
            await asyncio.sleep(0.01)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        ev["body_done"].set()
        return 0

    monkeypatch.setattr(app_runner, "_main_locked", body)
    return ev


def test_f5_lock_held_until_worker_thread_finishes(tmp_path, monkeypatch):
    """Разбор GPT 8252cc0 F5: вторая копия не получает замок, пока поток прохода первой ещё работает."""
    import threading
    path = str(tmp_path / "app_runner.lock")
    ev = _blocked_worker_body(monkeypatch)
    res = {}
    th = threading.Thread(target=lambda: res.setdefault("rc", _main(path, 0)))
    th.start()
    try:
        assert ev["body_done"].wait(5)
        time.sleep(0.2)
        assert app_runner._acquire_single_instance_lock(path, wait_sec=0) is None   # поток жив — замок держится
    finally:
        ev["release"].set()
        th.join(10)
    assert res["rc"] == 0
    fd = app_runner._acquire_single_instance_lock(path, wait_sec=0)                # поток закончил — замок свободен
    assert fd is not None
    os.close(fd)


def test_f5_cancelled_wait_keeps_lock_until_process_exit(tmp_path, monkeypatch):
    """Ожидание потоков прервано (отмена main): замок не отпущен ни пока поток жив, ни после — его снимет ядро при
    выходе процесса. (В Python 3.10 отменённый shutdown_default_executor всё равно дожидается потоков в finally.)"""
    import threading
    path = str(tmp_path / "app_runner.lock")
    ev = _blocked_worker_body(monkeypatch)
    seen, checked = {}, threading.Event()

    async def runner():
        task = asyncio.ensure_future(app_runner.main(signal_handler_installer=lambda loop, e: None, lock_path=path,
                                                     lock_wait_sec=0))
        while not ev["body_done"].is_set():
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        seen["kept"] = len(app_runner._KEPT_LOCKS)
        seen["held"] = app_runner._acquire_single_instance_lock(path, wait_sec=0) is None
        checked.set()

    def run():
        try:
            asyncio.run(runner())
        except RuntimeError:                                 # пул уже закрыт main — завершение asyncio.run
            pass

    th = threading.Thread(target=run)
    th.start()
    try:
        assert ev["body_done"].wait(5)
        time.sleep(0.4)                                      # отмена уже прошла, поток ещё жив
        assert app_runner._acquire_single_instance_lock(path, wait_sec=0) is None
    finally:
        ev["release"].set()
    assert checked.wait(10) and seen == {"kept": 1, "held": True}   # и после конца потока — до выхода процесса
    th.join(10)
    os.close(app_runner._KEPT_LOCKS.pop())                                         # «выход процесса» в тесте
    fd = app_runner._acquire_single_instance_lock(path, wait_sec=0)
    assert fd is not None
    os.close(fd)
