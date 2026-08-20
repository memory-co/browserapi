"""三种画面模式:**JPG / VNC / DOM**。

这个模块是这三个词**唯一的定义处** —— CLI、API、报错、观看端界面全从这里取。
一件事一个词,三层贯通;`screencast` / `xpra` / `rrweb` 只是历史别名和实现名,
不出现在使用者面前([c §9.1](../../docs/v2/works/c-view.md#91-使用者看到的是三个词))。

    JPG   Chromium 自己截,整屏图片      什么都显示得出来
    VNC   xpra 盯着 X 显示,区域图片      连续、跟手
    DOM   rrweb 传 DOM 变更,观看端重排   字最清楚、最省流量,但没有视频

**能用哪几种,起 session 的时候就定了**([c §9.3](../../docs/v2/works/c-view.md#93-能切到哪几条起-session-的时候就定了)):
VNC 要一个真实的 X 显示,而无头浏览器没有。所以起的时候那个选择不是
「用哪种」,是「以后能选哪几种」。
"""

from __future__ import annotations

from typing import NamedTuple

__all__ = ["JPG", "VNC", "DOM", "MODES", "Mode", "canon", "describe",
           "available_in", "needs_headed", "label"]

JPG = "jpg"
VNC = "vnc"
DOM = "dom"

#: 顺序即优先级:能用 VNC 就用 VNC,退而 JPG,再退 DOM。
#: **只在「默认选哪个」时用到** —— 运行时切换永远是人选的,不自动降级
#: ([c §9.5](../../docs/v2/works/c-view.md#95-切了必须说出来))。
MODES = (VNC, JPG, DOM)


class Mode(NamedTuple):
    name: str
    label: str          #: 界面上那一个词
    blurb: str          #: 一句话体感
    when: str           #: 什么时候选它
    impl: str           #: 实现叫什么 —— 只在日志和代码里出现
    headed: bool        #: 要不要一个真实的 X 显示


_M: dict[str, Mode] = {
    JPG: Mode(JPG, "JPG", "一张一张的图,什么都显示得出来",
              "拿不准就用它;有视频、有 canvas 的页面", "screencast", False),
    VNC: Mode(VNC, "VNC", "像远程桌面,连续、跟手",
              "动画、视频、大量滚动", "xpra", True),
    DOM: Mode(DOM, "DOM", "传的是网页本身,字最清楚、最省流量",
              "文字为主的页面;网络差的时候", "rrweb", False),
}

#: 旧名字继续认,但**不再回传给使用者** —— 报错和状态里一律用新词。
_ALIAS = {"screencast": JPG, "cdp": JPG, "jpeg": JPG,
          "xpra": VNC,
          "rrweb": DOM}


def canon(value: str | None) -> str | None:
    """把使用者给的词归一。**不认识就返回 None**,由调用方去报错 ——
    这里不猜、不兜底(见 `errors.py` 里那条"不静默降级")。"""
    if value is None:
        return None
    v = value.strip().lower()
    if v in _M:
        return v
    return _ALIAS.get(v)


def describe(name: str) -> Mode:
    return _M[name]


def label(name: str) -> str:
    m = _M.get(name)
    return m.label if m else name


def needs_headed(name: str) -> bool:
    return _M[name].headed


def available_in(*, headed: bool, remote: bool = False) -> tuple[str, ...]:
    """这台 session 上**能切到**的模式。

    `remote` 那条只有一个 CDP 端点,够不着对端的 X 显示 ——
    **少一个选项不是降级,是那条路上的全集**
    ([c §13](../../docs/v2/works/c-view.md#13-默认走哪条))。
    """
    if remote or not headed:
        return (JPG, DOM)
    return MODES


def choices() -> list[dict]:
    """给 API / 界面用的那张表。**界面不该自己再写一遍这些字。**"""
    return [{"name": m.name, "label": m.label, "blurb": m.blurb,
             "when": m.when, "needs_headed": m.headed}
            for m in (_M[k] for k in MODES)]
