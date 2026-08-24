"""打包前先把浏览器端构建出来 —— **不靠"记得先构建"**。

这是一个 in-tree 的 PEP 517 后端:除了在 setuptools 前面插一步之外什么都不做。

**为什么非要卡在这一步。** 这项目栽过一次:`.js` 没进 wheel,
而开发机上跑的是源码目录,一切正常 —— 只有干净安装才现形
([j §4.3](../docs/v2/works/j-layout.md#43-构建怎么接进-wheel))。
把构建接在打包这一刻,那种漏就**不可能发生**:
`webmuxd/_client/` 不在 git 里,每次打包都是现建的。

从 sdist 装的人不需要 Node —— sdist 里已经带着建好的那份。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from setuptools import build_meta as _upstream
from setuptools.build_meta import *  # noqa: F401,F403  —— 其余钩子原样透出

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "webmuxjs" / "client"
DEST = ROOT / "webmuxd" / "_client"

#: 注进页面里的那一段。和观看页平级、同一套工具链,**所以也同一个把关点**
#: —— 它漏进 wheel 的后果比观看页还隐蔽:光标、人的操作流水、
#: 前台漂移告警一起没了,而**一条错都不报**。
SIDE_SRC = ROOT / "webmuxjs" / "sidecar"
SIDE_DEST = ROOT / "webmuxd" / "_sidecar"

#: 装进被控浏览器的那个扩展。**产物是一个目录** —— `--load-extension`
#: 只收目录,所以这一份不能像 sidecar 那样拷一个文件了事。
EXT_SRC = ROOT / "webmuxjs" / "extension"
EXT_DEST = ROOT / "webmuxd" / "_extension"


def _say(msg: str) -> None:
    print(f"[webmuxd] {msg}", file=sys.stderr)


def build_client() -> None:
    """`npm run build` 之后把产物拷进包里。

    三种情况,**只有第三种是错误**:

    1. 有源码也有 npm → 现建一份。**发版走的是这条**,所以不可能漂移
    2. 建不了但 `webmuxd/_client/` 已经在 → 用它。从 sdist 装的人走这条,
       他们不需要 Node
    3. 两样都没有 → 打不出完整的包,当场停
    """
    npm = shutil.which("npm") if SRC.exists() else None

    if npm is None:
        if (DEST / "index.html").exists():
            why = "没有 webmuxjs/client/" if not SRC.exists() else "本机没有 npm"
            _say(f"{why},用已经建好的 webmuxd/_client/")
            return
        raise SystemExit(
            "浏览器端那份既建不了也没有现成的:"
            f"{'没有 ' + str(SRC) if not SRC.exists() else '本机没有 npm'},"
            f"而 {DEST}/index.html 也不在 —— 打不出完整的包。"
            "装 Node 18+ 再来,或者拿已经建好的 sdist 装")

    if not (SRC / "node_modules").exists():
        _say("npm install …")
        subprocess.run([npm, "install", "--no-audit", "--no-fund"],
                       cwd=SRC, check=True)
    _say("npm run build …")
    subprocess.run([npm, "run", "build"], cwd=SRC, check=True)

    dist = SRC / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit(f"构建完了但 {dist}/index.html 不在 —— 构建配置改坏了?")

    if DEST.exists():
        shutil.rmtree(DEST)
    shutil.copytree(dist, DEST)
    _say(f"浏览器端 → {DEST.relative_to(ROOT)}/({len(list(DEST.iterdir()))} 个文件)")


def build_sidecar() -> None:
    """页面里那段,规矩和 `build_client` 一样:能建就现建,建不了就用现成的,
    两样都没有当场停。"""
    npm = shutil.which("npm") if SIDE_SRC.exists() else None
    out = SIDE_DEST / "sidecar.js"

    if npm is None:
        if out.exists():
            why = "没有 webmuxjs/sidecar/" if not SIDE_SRC.exists() else "本机没有 npm"
            _say(f"{why},用已经建好的 {SIDE_DEST.name}/")
            return
        raise SystemExit(
            "页面里那段既建不了也没有现成的:"
            f"{'没有 ' + str(SIDE_SRC) if not SIDE_SRC.exists() else '本机没有 npm'},"
            f"而 {out} 也不在 —— 打不出完整的包。")

    if not (SIDE_SRC / "node_modules").exists():
        _say("npm install(sidecar)…")
        subprocess.run([npm, "install", "--no-audit", "--no-fund"],
                       cwd=SIDE_SRC, check=True)
    _say("npm run build(sidecar)…")
    subprocess.run([npm, "run", "build"], cwd=SIDE_SRC, check=True)

    built = SIDE_SRC / "dist" / "sidecar.js"
    if not built.exists():
        raise SystemExit(f"构建完了但 {built} 不在 —— 构建配置改坏了?")

    SIDE_DEST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, out)
    _say(f"页面里那段 → {out.relative_to(ROOT)}({out.stat().st_size} 字节)")


def build_extension() -> None:
    """那个扩展。规矩和前两样一样,只有一处不同:**产物是整个目录**。"""
    npm = shutil.which("npm") if EXT_SRC.exists() else None
    need = ("manifest.json", "sw.js")

    if npm is None:
        if all((EXT_DEST / f).exists() for f in need):
            why = "没有 webmuxjs/extension/" if not EXT_SRC.exists() else "本机没有 npm"
            _say(f"{why},用已经建好的 {EXT_DEST.name}/")
            return
        raise SystemExit(
            "那个扩展既建不了也没有现成的:"
            f"{'没有 ' + str(EXT_SRC) if not EXT_SRC.exists() else '本机没有 npm'},"
            f"而 {EXT_DEST}/ 里也不全 —— 打不出完整的包。")

    if not (EXT_SRC / "node_modules").exists():
        _say("npm install(extension)…")
        subprocess.run([npm, "install", "--no-audit", "--no-fund"],
                       cwd=EXT_SRC, check=True)
    _say("npm run build(extension)…")
    subprocess.run([npm, "run", "build"], cwd=EXT_SRC, check=True)

    dist = EXT_SRC / "dist"
    missing = [f for f in need if not (dist / f).exists()]
    if missing:
        raise SystemExit(f"构建完了但 {dist} 里少 {missing} —— 构建配置改坏了?")

    if EXT_DEST.exists():
        shutil.rmtree(EXT_DEST)
    shutil.copytree(dist, EXT_DEST)
    _say(f"扩展 → {EXT_DEST.relative_to(ROOT)}/({len(list(EXT_DEST.iterdir()))} 个文件)")


def _build_all() -> None:
    build_client()
    build_sidecar()
    build_extension()


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    _build_all()
    return _upstream.build_wheel(wheel_directory, config_settings, metadata_directory)


def build_sdist(sdist_directory, config_settings=None):
    _build_all()
    return _upstream.build_sdist(sdist_directory, config_settings)


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    build_client()
    return _upstream.build_editable(wheel_directory, config_settings, metadata_directory)


if __name__ == "__main__":         # `python _build/backend.py` 手动建一次
    build_client()
