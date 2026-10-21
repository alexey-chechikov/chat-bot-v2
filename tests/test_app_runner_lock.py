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
