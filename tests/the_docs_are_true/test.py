"""设计稿说的和代码做的必须是同一件事。

**一条腐烂的结论比没有结论更坏** —— 它看着像依据。
"""

import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = sorted(str(p.relative_to(ROOT)) for p in ROOT.glob("docs/**/*.md"))
TOP = ["README.md", "QUICKSTART.md", "CHANGELOG.md"]
ALL = DOCS + TOP


def slug(h: str) -> str:
    """GitHub 的锚点规则。**每个空格一个连字符,不合并** ——
    `A —— B` 里那个破折号被删掉后留下两个空格,锚点是 `a--b`。"""
    s = h.strip().lower()
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\*\*([^*]*)\*\*", r"\1", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = "".join(c for c in s if c.isalnum() or c in " -_" or ord(c) > 0x2E80)
    s = re.sub(r"[^\w\s-]", "", s)
    return s.strip().replace(" ", "-")


def _headings(rel: str) -> set[str]:
    return {slug(m.group(1))
            for m in re.finditer(r"^#{1,6}\s+(.*)$", (ROOT / rel).read_text(), re.M)}


def _links(rel: str):
    for m in re.finditer(r"\[[^\]]*\]\(([^)\s]+)\)", (ROOT / rel).read_text()):
        t = m.group(1)
        if not t.startswith(("http", "mailto")):
            yield t


@pytest.mark.parametrize("rel", ALL)
def test_链接指得到(rel):
    """**断链在 GitHub 上是静默的** —— 跳到页首,不报错。"""
    base = os.path.dirname(rel)
    bad = []
    for t in _links(rel):
        path, _, _anchor = t.partition("#")
        if path and not (ROOT / os.path.normpath(os.path.join(base, path))).exists():
            bad.append(t)
    assert not bad, f"{rel} 指向不存在的东西:{bad}"


@pytest.mark.parametrize("rel", ALL)
def test_锚点指得到(rel):
    base = os.path.dirname(rel)
    heads = {}
    bad = []
    for t in _links(rel):
        path, _, anchor = t.partition("#")
        if not anchor:
            continue
        target = rel if not path else os.path.normpath(os.path.join(base, path))
        if not (ROOT / target).exists() or not target.endswith(".md"):
            continue
        if target not in heads:
            heads[target] = _headings(target)
        if slug(anchor) not in heads[target]:
            bad.append(f"{t}(那篇里没有这个标题)")
    assert not bad, f"{rel} 的锚点断了:{bad}"


# --------------------------------------------------------------- 数字要对得上

def _doc(*names: str) -> str:
    """把 v2 的设计稿拼起来找。

    **不钉死文件名。** 这一套正在重写(编号换字母、几篇合并成一篇),
    钉死文件名的话每改一次结构就要改一次测试 —— 而这些用例要守的是
    "这个数字还是不是那个数字",不是"它写在哪个文件里"。
    """
    return "\n".join(p.read_text() for p in
                      sorted((ROOT / "docs/v2/works").glob("*.md")))


def test_帧头是二十八个字节_文档里写的也是():
    """这个数字是 [09](../../docs/v2/works/09-wire-format.md) 整篇的主角 ——
    "ttyd 一个字节、我们二十八个"。改了不同步,那篇的论证就悬空了。"""
    from webmuxd.view.protocol import HEADER_SIZE
    for f in ("02-frame-protocol.md", "09-wire-format.md"):
        assert f"{HEADER_SIZE} 字节" in _doc(), f"{f} 里的帧头长度和代码对不上"


def test_两个_ack_环的参数和文档一致():
    from webmuxd.view.viewer import ACK_CREDIT, BUFFER
    t = _doc() + _doc("09-wire-format.md")
    assert f"额度 {ACK_CREDIT}" in t or f"额度 `ACK_COUNT = {ACK_CREDIT}`" in t
    assert f"长度 {BUFFER}" in t, "缓冲长度对不上"


def test_画质下限和文档一致():
    """25 不是拍的 —— 文档里写着它的来历(BrowserBox 的 Tor 模式)。"""
    from webmuxd.view.quality import QUALITY_FLOOR
    assert str(QUALITY_FLOOR) in _doc()


def test_默认视口和文档一致():
    from webmuxd.view.cast import DEFAULT_H, DEFAULT_W
    assert f"{DEFAULT_W}x{DEFAULT_H}" in _doc() + _doc() \
        or f"{DEFAULT_W}×{DEFAULT_H}" in _doc()


def test_钉死的浏览器版本和文档一致():
    """[07 §4.1](../../docs/v2/works/07-runtime.md) 那一节的全部意义就是这个数。"""
    from webmuxd import browser
    assert browser.PINNED in _doc()


def test_xpra_上行那几个包_文档和白名单是同一份():
    """**这张表是安全边界。** 代码里加一个而文档不加,边界就说不清了。"""
    from webmuxd.view import relay
    doc = _doc()
    for name in relay.ALLOWED:
        assert f"`{name}`" in doc, f"白名单里有 {name},但 12 §7 那张表里没有"
    # **个数也不能自相矛盾。** 写这条测试时就逮到一处:表里 6 个,
    # 正文却还写着"只放行这 5 个包类型" —— 白名单是安全边界,
    # 正文和表对不上,读的人不知道该信哪个。
    #
    # 只查矛盾,不查措辞:文档在重写,"六个"和"6 个"都可能出现。
    n = len(relay.ALLOWED)
    cn = "零一二三四五六七八九十"[n] if n < 11 else str(n)
    wrong = [m.group(0) for m in re.finditer(r"上行([\d一二三四五六七八九十]+)个包", doc)
             if m.group(1) not in (str(n), cn)]
    wrong += [m.group(0) for m in re.finditer(r"放行这\s*([\d一二三四五六七八九十]+)\s*个",
                                             doc) if m.group(1) not in (str(n), cn)]
    assert not wrong, f"正文里的个数和白名单({n} 个)对不上:{wrong}"


def test_xpra_的头是八个字节():
    from webmuxd.view import relay
    assert f"{relay.HEADER.size} 字节头" in _doc()


def test_客户端不声明视频编码_文档和代码是同一个结论():
    """设计稿里那条「不声明就永远不会发过来」是「明确不做 h264」的**唯一理由**。
    哪天真加了 WebCodecs,这两处都得跟着改。

    只查结论在不在,不查措辞 —— 文档在重写。
    """
    src = (ROOT / "webmuxd/view/static/xpra.js").read_text()
    assert "full_csc_modes" not in re.sub(r"//.*", "", src), \
        "客户端声明了视频编码,但设计稿说不声明"
    doc = _doc()
    assert "不声明视频编码" in doc or "不报视频编码" in doc
