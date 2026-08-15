"""起一个**真容器**的共享脚手架 —— 两个镜像场景共用。

不 mock 任何东西:这两个场景的全部价值就在于"我们和别人做的镜像的交界处",
换成假的等于什么都没测。
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from contextlib import contextmanager

import pytest

from webmuxd.runtime.container import ContainerRuntime


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def need_image(image: str) -> None:
    """没 docker 或没这个镜像就**跳过,不是失败** —— 镜像要 build 出来才有,
    而 build 一次是 GB 级的事,不该挡住其他人跑测试。"""
    if not shutil.which("docker"):
        pytest.skip("没有 docker")
    r = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", image],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"本机没有 {image} —— 先 docker build docker/<目录>/")


def sweep(prefix: str) -> None:
    """把上一轮遗留的容器清掉再开跑。

    **场景之间必须互不影响。** 用例中途断言失败时,`finally` 不一定跑得到;
    留下的容器占着端口,会让下一轮以一个完全无关的症状失败(容器起来就退出),
    查半天 —— 这种"上一轮的尸体害死这一轮"的坑,自己先堵上。
    """
    if not shutil.which("docker"):
        return
    out = subprocess.run(["docker", "ps", "-aq", "--filter", f"name={prefix}"],
                         capture_output=True, text=True).stdout.split()
    if out:
        subprocess.run(["docker", "rm", "-f", *out], capture_output=True)


@contextmanager
def session_on(image: str, sid: str, url: str = "https://example.com"):
    """真起一个容器 + sessiond,`with` 退出时收干净。"""
    from webmuxd.client.session import Session

    impl = ContainerRuntime(image=image)
    api, win = free_port(), free_port()
    handle = impl.start(sid, api_port=api, view_port=win, url=url, password="testpw123")
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                sess = Session(sid, handle.api_url)
                break
            except Exception:
                time.sleep(1)
        else:
            raise AssertionError("sessiond 起来了但连不上")
        yield handle, sess
    finally:
        impl.stop(handle)
