"""`view/` —— 画面这一半,v2 新增的全部代码。

docs/v2/works/01-frame-source.md:v1 的画面是别人的 VNC,我们只报 URL;
v2 用 CDP 的 `Page.startScreencast` 自己产帧、用 `Input.*` 自己收输入。

**这个包之外一行都没动。** `core/`(cdp / tabs / locate / observe / act / log)
和 `client/` 的三个对象和 v1 完全一样 —— 定位、观测、日志、tab 表和画面从哪来
无关([08 §2](../../docs/v2/works/08-migration.md))。

| 文件 | 管什么 |
| --- | --- |
| `protocol.py` | 28 字节帧头 |
| `cast.py` | screencast 的开关和搬家、环 A 的 ack、扇出 |
| `viewer.py` | 一条观看连接:额度、缓冲、RTT |
| `quality.py` | RTT 自适应降质 |
| `input.py` | 输入翻译 —— **安全收口** |
| `cursor.py` | 光标探针 + 白名单 |
"""

from webmuxd.view.cast import Screencaster
from webmuxd.view.input import Translator
from webmuxd.view.protocol import HEADER_SIZE, build_header, parse_header
from webmuxd.view.quality import Adaptor
from webmuxd.view.viewer import Viewer

__all__ = ["Screencaster", "Translator", "Viewer", "Adaptor",
           "build_header", "parse_header", "HEADER_SIZE"]
