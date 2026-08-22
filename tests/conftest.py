"""共享 fixture —— 一个真的 headless Chromium,session 级。

    webmuxd install && pytest -q

浏览器优先用 `webmuxd install` 下的那个**钉死版本**,没有就退到系统里那个 ——
版本在 `config.PINNED`([h §4.1](../docs/v2/works/h-runtime.md))。
"""

import asyncio
import contextlib
import os
import shutil
import socket
import subprocess
import time

import pytest

from webmuxd import config
from webmuxd import install as install_mod
from webmuxd.cdp import CDP

CHROMIUM = config.find() or config.find_system()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def chromium_endpoint():
    """起一个 Chromium,返回 http://127.0.0.1:<port>。"""
    if not CHROMIUM:
        pytest.skip("本机没有浏览器 —— 跑 `webmuxd install` 下一个")

    port = _free_port()
    profile = os.path.join("/tmp", f"wm-{port}")
    proc = subprocess.Popen(
        [
            CHROMIUM,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    endpoint = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    while time.time() < deadline:
        with contextlib.suppress(Exception):
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        if proc.poll() is not None:
            pytest.fail("chromium 起不来")
        time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail("chromium 30s 内没监听")

    yield endpoint
    proc.terminate()
    with contextlib.suppress(Exception):
        proc.wait(timeout=5)
    # **profile 目录也要收。** 一个 chrome profile 几十兆,一轮测试几十个 ——
    # 不收的话它只是攒着,直到有人发现 /tmp 有几百个 `wm-*`
    shutil.rmtree(profile, ignore_errors=True)


@pytest.fixture
async def cdp(chromium_endpoint):
    conn = await CDP.connect(chromium_endpoint)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def page(cdp):
    """一个附着好的 page target,返回 (target_id, session_id)。"""
    r = await cdp.send("Target.createTarget", {"url": "about:blank"})
    tid = r["targetId"]
    a = await cdp.send("Target.attachToTarget", {"targetId": tid, "flatten": True})
    sid = a["sessionId"]
    try:
        yield tid, sid
    finally:
        with contextlib.suppress(Exception):
            await cdp.send("Target.closeTarget", {"targetId": tid})
