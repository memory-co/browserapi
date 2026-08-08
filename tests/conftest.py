"""测试跑在容器内 —— Chromium 的 Host 头校验挡掉容器外的 CDP 访问
(docs/v1/works/01-container.md §3 实测)。所以这里直接在同容器起 Chromium。

    docker run --rm -v "$PWD":/src webmuxd-dev pytest
"""

import asyncio
import contextlib
import os
import shutil
import socket
import subprocess
import time

import pytest

from webmuxd.core.cdp import CDP

CHROMIUM = next(
    (p for p in ("chromium-browser", "chromium", "chrome") if shutil.which(p)), None
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def chromium_endpoint():
    """起一个 Chromium,返回 http://127.0.0.1:<port>。"""
    if not CHROMIUM:
        pytest.skip("容器里没有 chromium —— 用 webmuxd-dev 镜像跑")

    port = _free_port()
    proc = subprocess.Popen(
        [
            CHROMIUM,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            "--user-data-dir=" + os.path.join("/tmp", f"wm-{port}"),
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
