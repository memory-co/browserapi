"""目录扁平之后,层靠这几条测试守。

`docs/v2/works/j-layout.md` §5 五条依赖规矩 + §6 两条 docstring 规矩。
不跑浏览器,**永远会跑**。
"""

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
PKG = ROOT / "webmuxd"

#: [j §5](../../docs/v2/works/j-layout.md#5-依赖方向扁平之后层要靠规矩守) 那张表。
#: **只能往下 import,不能往上。**
LAYERS = [
    "models exceptions logfmt",
    "processes config cdp log",
    "tabs act locate capture sidecar extension browser_ui frames quality input cursor "
    "jpg xpra rrweb",
    "screen sessions",
    "serve",
    "api cli install",
]
LAYER = {name: i for i, row in enumerate(LAYERS) for name in row.split()}

FILES = sorted(p for p in PKG.glob("*.py") if p.stem not in ("__init__", "__main__"))


def _imports(path: pathlib.Path) -> list[tuple[str, int]]:
    """这个文件真正 import 的本项目模块。

    **`if TYPE_CHECKING:` 里的不算** —— 那些只为类型标注存在,运行时不发生,
    也就不构成依赖。`browser_ui.py` 引 `sessions.Session` 就是这一种。
    """
    tree = ast.parse(path.read_text())
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
            skip |= {id(c) for c in ast.walk(node)}

    out = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        mods: list[str] = []
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("webmuxd"):
            parts = node.module.split(".")
            mods = [parts[1]] if len(parts) > 1 else [a.name for a in node.names]
        elif isinstance(node, ast.Import):
            mods = [a.name.split(".")[1] for a in node.names
                    if a.name.startswith("webmuxd.")]
        out += [(m, node.lineno) for m in mods if m in LAYER]
    return out


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_每个文件都在层里(path):
    """新加一个文件就得想清楚它在第几层 —— **想不清楚就是还没设计完。**"""
    assert path.stem in LAYER, (
        f"{path.name} 不在 j §5 那张表里。加文件要同时想清楚它属于哪一层,"
        "否则「只能往下 import」这条就没法验了")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_只往下_import(path):
    me = LAYER.get(path.stem)
    if me is None:
        pytest.skip("上一条会报")
    bad = [(m, ln) for m, ln in _imports(path) if LAYER[m] > me]
    assert not bad, "\n".join(
        f"{path.name}:{ln} import 了 {m}(第 {me} 层 → 第 {LAYER[m]} 层)"
        for m, ln in bad)


def test_models_只认识_exceptions():
    """**它永远在最底下。** 一旦它开始 import `cdp.py`,它就不再是模型层了。"""
    got = {m for m, _ in _imports(PKG / "models.py")}
    assert got <= {"exceptions"}, f"models.py 还 import 了 {got - {'exceptions'}}"


@pytest.mark.parametrize("who", ["api", "cli"])
def test_给人用的那两个不认识_serve(who):
    """**SDK 要能连别的机器上的服务端。**

    一旦 `api.py` import 了进程内的 `serve.py`,那条路就断了 ——
    而且断得很隐蔽:本机测试全过,换台机器才发现。
    """
    got = {m for m, _ in _imports(PKG / f"{who}.py")}
    assert "serve" not in got, f"{who}.py import 了 serve.py"


def test_screen_不认识_input():
    """输入是**接缝的另一侧**,不是 screen 的下一层
    ([b §1](../../docs/v2/works/b-input.md#1-收口在哪))。

    画面从浏览器出来,输入往浏览器进去 —— 两个方向。合在一起写,
    「只读地看」这件事就没有结构上的保证了。
    """
    got = {m for m, _ in _imports(PKG / "screen.py")}
    assert "input" not in got


@pytest.mark.parametrize("leg", ["jpg", "xpra", "rrweb"])
def test_三条腿互不认识(leg):
    """**谁也不是谁的基础。** 一旦串起来,「换一条」就不再是换一条。"""
    others = {"jpg", "xpra", "rrweb"} - {leg}
    got = {m for m, _ in _imports(PKG / f"{leg}.py")}
    assert not (got & others), f"{leg}.py import 了 {got & others}"


def test_那个_binding_两边写的是同一个名字():
    """**页面里那个函数名,Python 和 TypeScript 各写了一遍。**

    不一样的后果特别难查:`addBinding` 照样成功、页面里那个函数照样在、
    页面照样调它 —— **服务端一条都收不到,而且不报错**。表现是光标永远
    是箭头、人的操作不进流水、前台漂了没人知道,三样一起没。

    两处各写一遍是没法避免的(一个在 Python 里发 CDP,一个在页面里被调),
    那就把"它们必须一样"这件事验起来。
    """
    from webmuxd import sidecar

    ts = (ROOT / "webmuxjs" / "sidecar" / "src" / "wire.ts").read_text()
    m = re.search(r'export const BINDING = "([^"]+)"', ts)
    assert m, "wire.ts 里那行 `export const BINDING` 找不到了"
    assert m.group(1) == sidecar.BINDING, \
        f"两边对不上:wire.ts 是 {m.group(1)!r},sidecar.py 是 {sidecar.BINDING!r}"


# --------------------------------------------------------------------------
# §6 一句话说清自己
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_每个文件都有一句话(path):
    """**三十来个文件平铺,docstring 第一行就是目录。**"""
    doc = ast.get_docstring(ast.parse(path.read_text()))
    assert doc and doc.splitlines()[0].strip(), \
        f"{path.name} 没有 docstring —— 文件名说了一半,另一半在那句话里"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_引到的设计稿都在(path):
    """**指向已删掉的编号篇比不指更坏** —— 它看着像依据。"""
    missing = []
    for rel in re.findall(r"\((\.\./[^)\s]+\.md)(?:#[^)]*)?\)", path.read_text()):
        if not (path.parent / rel).resolve().exists():
            missing.append(rel)
    assert not missing, f"{path.name} 指向不存在的设计稿:{missing}"


# --------------------------------------------------------------------------
# 一件事一个词,三层贯通
# --------------------------------------------------------------------------

FACES = ["cli.py", "serve.py", "api.py"]


@pytest.mark.parametrize("name", FACES)
def test_给人看的那几个文件里不出现实现名(name):
    """**使用者看到的是 JPG / VNC / DOM。**

    `screencast` / `xpra` / `rrweb` 是实现名,只该出现在日志和代码里
    ([c §9.1](../../docs/v2/works/c-view.md#91-使用者看到的是三个词))。
    这条以前是靠自觉的,`webmuxd info` 就悄悄印过 "xpra(默认),screencast"。

    只看**会被印出去的字符串**。三类不算:

    - `import xpra` / `xpra_ok` —— 那是代码,不是给人看的字
    - docstring —— 写给读代码的人的
    - 路由和文件名(`/channel/rrweb`、`/api/rrweb.js`)—— 那是**线上的名字**,
      协议的一部分,改它是另一件事
    """
    src = (PKG / name).read_text()
    tree = ast.parse(src)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            d = node.body[0] if node.body else None
            if (isinstance(d, ast.Expr) and isinstance(d.value, ast.Constant)
                    and isinstance(d.value.value, str)):
                docs.add(id(d.value))

    def is_wire(v: str) -> bool:
        return (v.startswith("/") or "://" in v
                or v.endswith((".js", ".css", ".json")))

    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docs or is_wire(node.value):
            continue
        for impl in ("screencast", "rrweb"):
            # 旧名字要继续认,所以别名表里出现是对的
            if impl in node.value and "别名" not in node.value:
                bad.append((node.lineno, impl, node.value[:60]))
    assert not bad, "\n".join(f"{name}:{ln} 里印了实现名 {impl}:{v}"
                              for ln, impl, v in bad)
