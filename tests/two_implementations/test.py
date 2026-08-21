"""两个实现之间的对拍,以及"浏览器端建了没有"。

这里**生成** fixture 并断言它和仓库里那份一样 ——
所以 Python 那边改了格式,这条先红;重新生成之后,JS 那边跟着红。
两边一起红,而不是悄悄漂移。
"""

import json
import pathlib
import subprocess

import pytest

from webmuxd import frames
from webmuxd.act import _MODIFIER_BITS

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIX = ROOT / "webmuxjs" / "client" / "fixtures"
CLIENT = ROOT / "webmuxjs" / "client"

#: 出现在 fixture 里的那几个 target,**故意包含畸形的**。
TARGETS = [
    (1, 1, "ABCDEF0123456789ABCDEF0123456789"),
    (0, 0, ""),
    (7, 4294967295, "0123456789abcdef0123456789abcdef"),
    (65535, 42, "ff"),                       # 短的,两边都补零
    (3, 9, "z" * 32),                        # 不是 hex,两边都当零
]


def _frame_header() -> dict:
    return {
        "_": "由 tests/two_implementations/ 生成 —— 别手改。Python 是这份的权威。",
        "header_size": frames.HEADER_SIZE,
        "cases": [{"cast": c, "frame": f, "target": t,
                   "bytes": list(frames.build_header(c, f, t))}
                  for c, f, t in TARGETS],
    }


def _upstream() -> dict:
    return {
        "_": "由 tests/two_implementations/ 生成 —— 别手改。",
        "types": sorted(frames.UPSTREAM),
        "modifiers": {k: v for k, v in _MODIFIER_BITS.items()
                      if k in ("Alt", "Control", "Meta", "Shift")},
    }


GENERATED = {"frame-header.json": _frame_header, "upstream.json": _upstream}


@pytest.mark.parametrize("name", sorted(GENERATED))
def test_fixture_和_python_现在编出来的一致(name):
    """**这条红了就是格式变了。**

    重新生成:`python -m tests.two_implementations.regen`,
    然后去 `webmuxjs/client/` 跑 `npm test` —— 那边会跟着红,
    这正是要的效果。
    """
    want = GENERATED[name]()
    got = json.loads((FIX / name).read_text())
    assert got == want, (
        f"{name} 和 Python 现在编出来的对不上 —— 格式变了就重新生成,"
        "别手改 fixture")


def test_那张上行白名单两边是同一张():
    """**收口就是这张表本身。** 客户端多认一个,服务端就多一个洞。"""
    js = (CLIENT / "src" / "protocol" / "messages.ts").read_text()
    for t in frames.UPSTREAM:
        assert f'"{t}"' in js, f"客户端那张表里没有 {t}"


def test_那条通道结构上没有上行_两边一样():
    """服务端 handler 里没有接收端,客户端文件里没有发送函数。"""
    js = (CLIENT / "src" / "channel" / "rrweb.ts").read_text()
    # 去掉注释再看,免得文档里提一句 send 就误报
    import re
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    code = re.sub(r"//.*", "", code)
    assert ".send(" not in code, "rrweb.ts 里出现了发送 —— 那条通道该是只下行的"


# --------------------------------------------------------------------------
# 浏览器端建了没有
# --------------------------------------------------------------------------

def _built_dir() -> pathlib.Path | None:
    from webmuxd import serve
    for d in (serve._BUILT, serve._DEV):
        if (d / "index.html").exists():
            return d
    return None


def test_浏览器端那份建出来了():
    """**不能靠"记得先构建"。** 这项目栽过一次 `.js` 没进 wheel ——
    而开发机上跑的是源码目录,一切正常,只有干净安装才现形。

    没建就在 `webmuxjs/client/` 里跑 `npm install && npm run build`,
    或者在仓库根跑 `python _build/backend.py`。
    """
    d = _built_dir()
    assert d is not None, (
        "浏览器端那份还没构建 —— 跑 `python _build/backend.py`")


def test_构建产物不比源码旧():
    """源码改了没重建,页面上跑的还是上一版 —— **看着像代码没生效**。"""
    d = _built_dir()
    if d is None:
        pytest.skip("上一条会报")
    built = min(p.stat().st_mtime for p in d.iterdir() if p.is_file())
    newest = max(p.stat().st_mtime
                 for p in (CLIENT / "src").rglob("*.ts"))
    newest = max(newest, (CLIENT / "index.html").stat().st_mtime)
    assert built >= newest, (
        "webmuxjs/client/src/ 比构建产物新 —— 重新跑 `python _build/backend.py`")


def test_产物里没有源码路径泄漏():
    """sourcemap 和绝对路径不该进发出去的那份。"""
    d = _built_dir()
    if d is None:
        pytest.skip("上一条会报")
    for p in d.iterdir():
        if p.suffix in (".js", ".html"):
            assert str(ROOT) not in p.read_text(errors="replace"), \
                f"{p.name} 里带着构建机的绝对路径"
