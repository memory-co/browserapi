# channel · 画面出去、输入进来

**一句话**:这是最大的一个域(约 2200 行),而它今天**摊在九个平级文件里**,
其中三个是"三条腿",另外六个各管一小段。

## 1. 今天散在哪

| 今天 | 多大 | 干什么 |
| --- | --- | --- |
| `screen.py` | 577 | 编排:跟 tab、管观看者、背压、切换 |
| `xpra.py` | 507 | VNC 那条:起 xpra + 8 字节头 + 上行白名单 |
| `rrweb.py` | 586 | DOM 那条:注入记录器 + 事件流 + 资源转发 |
| `jpg.py` | 76 | JPG 那条:`Page.startScreencast` |
| `frames.py` | 66 | 28 字节头 + 上行白名单 |
| `quality.py` | 102 | RTT 自适应降质 |
| `input.py` | 173 | DOM 事件 → `Input.*` |
| `cursor.py` | 30 | 光标白名单(算形状那段在 sidecar) |
| `sidecar.py` | 105 | 注进页面里那段的装配 |
| `models.py` 里下行六种 + `FrameHeader` + `ViewMode` + 三个词 | ~160 | 形状和词表 |

`screen ↔ rrweb` 相关度 **0.67**、`screen ↔ processes` **0.67**、
`xpra ↔ processes` **0.67** —— 这三对是同一件事被切开的直接证据。

## 2. 该长成什么样

```
channel/
  README.md
  shape.py     Hello / Cast / Meta / QualityChanged / ModeInfo / ModeError / CursorChanged
  words.py     三个词 + ViewMode + canon/available_in/needs_headed —— **规则,不是数据**
  cast.py      编排:跟 tab、观看者、额度、背压、切换
  jpg.py       一条腿
  vnc.py       一条腿(xpra)
  dom.py       一条腿(rrweb)
  frame.py     28 字节头 + 上行白名单 + `FrameHeader`
  input.py     输入 + 光标白名单
  sidecar.py   注进页面里那段的装配(那段 JS 在 webmuxjs/sidecar/)
  http.py      /channel/* · /api/view · /api/mode
  cli.py       attach / capture 里画面那半
```

**三条腿仍然是三个文件**,而且互不认识 —— 那条规矩今天就有测试守着
(`tests/the_layout_holds` 的"三条腿互不认识"),搬家之后照旧:
**谁也不是谁的基础,一旦串起来,"换一条"就不再是换一条。**

## 3. `words.py` 不是数据,是规则

三个词(`JPG` / `VNC` / `DOM`)加上:

- `canon()` —— 旧名字继续认(`screencast`/`cdp`/`jpeg` → `jpg`),
  但**不再回传给使用者**;不认识就返回 `None`,**不猜、不兜底**
- `MODES` 的顺序 —— **顺序即优先级**,只在"默认选哪个"时用到;
  运行时切换永远是人选的,**不自动降级**
- `available_in()` —— `remote` 那条够不着对端的 X 显示,
  **少一个选项不是降级,是那条路上的全集**
- `mode_choices()` —— **界面不该自己再写一遍这些字**

它今天埋在 993 行的中段,后果很具体:

> **想加第四种画面的人,不知道要改几处。**

## 4. `shape.py` 里那份有第二个实现

下行那六种消息是这个项目**唯一一处"同一个形状写了两遍"**的地方:

```
channel/shape.py                          ← Python 这份
webmuxjs/client/src/protocol/messages.ts  ← TS 那份
webmuxjs/server/protocol/frames.md §4     ← 契约
```

两遍不一致的后果**不是报错,是静默**:TS 那边读到 `undefined`,画面就那么停着,
而两边各自的测试都是绿的。所以 [`two_implementations/`](../../../tests/two_implementations/)
拿 fixture 逐字节对拍 —— **那套对拍只对这一份有意义**。

由此还能立一条:**`channel/shape.py` 里一律没有 `from_json`。**
下行是单向的:服务端写、TS 读,Python 永远不需要读回来。
今天全文 `to_json` 有 18 个而 `from_json` 只有 8 个,
但**看不出哪个缺失是设计、哪个是漏** —— 分开之后这句话自己就说清楚了。

## 5. 上行和下行不对称,而且是有意的

- **上行**(`frame.py` 那张白名单):观看者**能表达什么** ——
  它是**安全边界**,白名单不是黑名单([b](../works/b-input.md))
- **下行**(`shape.py`):我们**会告诉观看者什么**

放一个文件里会让人以为它们对称。

## 6. ↔ 别处

| | |
| --- | --- |
| 三条腿 | [c](../works/c-view.md) |
| 降质 | [c1](../works/c1-quality.md) |
| 线上格式 | [e1](../works/e1-wire-format.md) |
| 输入收口在哪 | [b](../works/b-input.md) |
