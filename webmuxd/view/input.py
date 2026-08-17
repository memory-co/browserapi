"""输入翻译 —— **整个安全模型的收口**。

docs/v2/works/03-input.md:观看者能对远端做的事,全部被限制在 CDP 的 `Input`
域这几个命令里。他**拿不到 DOM,执行不了脚本,发不出任意 CDP 命令** ——
能表达的全部意图就是"在某个坐标点一下""按某个键",和坐在真实浏览器前的人
完全等价,不多不少。

所以这个文件里只会出现 `Input.*`,而且是写死的四个([03 §1](../../docs/v2/works/03-input.md))。

**键盘用带 `text` 的 `keyDown`,不是 `Input.insertText`**([03 §2](../../docs/v2/works/03-input.md)):
两者都能把字符送进输入框,但只有前者会让远端页面收到真实的 `keydown` ——
监听按键的页面(快捷键、搜索框联想、编辑器)才能正常工作。
`insertText` 留给它该干的两件事:**IME 提交**和**粘贴**。
"""

from __future__ import annotations

from typing import Any

from webmuxd.core.cdp import CDP

#: CDP 的修饰键位。
ALT, CTRL, META, SHIFT = 1, 2, 4, 8

_MOUSE_TYPES = {"mousePressed", "mouseReleased", "mouseMoved"}
_BUTTONS = {0: "left", 1: "middle", 2: "right", 3: "back", 4: "forward"}

#: 特殊键的 `text`。给了 `text` 页面才收得到"打进去了"这件事;
#: 没在表里的功能键(方向键、F1…)**不给 text**,否则会往输入框里塞垃圾字符。
_TEXT_FOR = {"Enter": "\r", "Tab": "\t"}

#: 常见键的 Windows virtual key code。缺了页面的 `e.keyCode` 判断会失灵。
_VK = {
    "Backspace": 8, "Tab": 9, "Enter": 13, "Shift": 16, "Control": 17, "Alt": 18,
    "Escape": 27, "Space": 32, "PageUp": 33, "PageDown": 34, "End": 35, "Home": 36,
    "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40,
    "Insert": 45, "Delete": 46, "Meta": 91,
}


def _vk(key: str, code: str) -> int:
    if key in _VK:
        return _VK[key]
    if len(key) == 1:
        return ord(key.upper())
    if code.startswith("Key") and len(code) == 4:
        return ord(code[3])
    if code.startswith("Digit") and len(code) == 6:
        return ord(code[5])
    return 0


def _int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class Translator:
    """把归一化的上行消息翻译成 `Input.*`。

    `session_id` 指向正在被观看的那个 target —— 打不到别的 tab 上去。
    """

    def __init__(self, cdp: CDP, session_id: str) -> None:
        self.cdp = cdp
        self.sid = session_id

    async def handle(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "mouse":
            await self._mouse(msg)
        elif kind == "wheel":
            await self._wheel(msg)
        elif kind == "key":
            await self._key(msg)
        elif kind == "text":
            await self._text(msg)
        # 别的一律忽略 —— 白名单,不是黑名单

    # ------------------------------------------------------------------ 鼠标

    async def _mouse(self, m: dict) -> None:
        type_ = {"move": "mouseMoved", "down": "mousePressed",
                 "up": "mouseReleased"}.get(str(m.get("event")), "")
        if type_ not in _MOUSE_TYPES:
            return
        btn = _BUTTONS.get(_int(m.get("button")), "left")
        params: dict[str, Any] = {
            "type": type_,
            # **CSS 像素** —— dsf 只影响帧的物理尺寸,不影响这里(02 §4③)
            "x": _num(m.get("x")), "y": _num(m.get("y")),
            "modifiers": _int(m.get("modifiers")) & 0xF,
            "buttons": _int(m.get("buttons")),
            "clickCount": max(0, min(3, _int(m.get("clicks"), 1))),
        }
        params["button"] = btn if type_ != "mouseMoved" else "none"
        if type_ == "mouseMoved":
            params["clickCount"] = 0
        await self.cdp.send("Input.dispatchMouseEvent", params, session_id=self.sid)

    async def _wheel(self, m: dict) -> None:
        await self.cdp.send("Input.dispatchMouseEvent", {
            "type": "mouseWheel",
            "x": _num(m.get("x")), "y": _num(m.get("y")),
            "deltaX": _num(m.get("dx")), "deltaY": _num(m.get("dy")),
            "modifiers": _int(m.get("modifiers")) & 0xF,
            "button": "none", "buttons": 0, "clickCount": 0,
        }, session_id=self.sid)

    # ------------------------------------------------------------------ 键盘

    async def _key(self, m: dict) -> None:
        down = str(m.get("event")) == "down"
        key = str(m.get("key") or "")[:32]
        code = str(m.get("code") or "")[:32]
        mods = _int(m.get("modifiers")) & 0xF
        if not key:
            return

        text = m.get("text")
        if text is None:
            text = _TEXT_FOR.get(key, key if len(key) == 1 else "")
        text = str(text)[:8]
        # Ctrl/Meta 组合键不带 text —— 那是快捷键,不是往框里打字
        if mods & (CTRL | META):
            text = ""

        params: dict[str, Any] = {
            "type": "keyDown" if down else "keyUp",
            "key": key, "code": code, "modifiers": mods,
            "windowsVirtualKeyCode": _vk(key, code),
            "nativeVirtualKeyCode": _vk(key, code),
        }
        if down and text:
            # **带 text 的 keyDown** —— 页面收到的是真实 keydown,
            # 而字符也进得去。这是 03 §2 那张表的结论。
            params["text"] = text
            params["unmodifiedText"] = text
        await self.cdp.send("Input.dispatchKeyEvent", params, session_id=self.sid)

    async def _text(self, m: dict) -> None:
        """IME 提交和粘贴走这条 —— 那两种场景本来就不该逐字符伪造按键。"""
        text = str(m.get("text") or "")
        if not text:
            return
        await self.cdp.send("Input.insertText", {"text": text[:100_000]},
                            session_id=self.sid)
