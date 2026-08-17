# pixels_on_a_wire — 画面是我们自己产的

## 这个场景在测什么

v2 把画面从"别人的 VNC"换成了"CDP 的 `Page.startScreencast`"
([docs/v2/works/01](../../docs/v2/works/01-frame-source.md))。这一换,
画面和输入两条链路第一次全在我们手里 —— 所以它们也第一次**需要被测**。
锁的是这几个拐点:

1. **帧头是定长 28 字节,不是 JSON。** `targetId` 进头部不是装饰:客户端靠它
   丢掉切 tab 前的残帧。`frameId` 单调递增,载荷是真的 JPEG。
2. **两个 ack 环必须解耦。** 一个故意不回 ack 的客户端只能拿到"额度 + 缓冲"那么多帧,
   而**同时连着的正常客户端不受影响** —— 这是"一个卡住的观看者不能拖垮别人"的唯一证据。
3. **`active` 就是 screencast 挂在哪个 target 上。** 切 tab 之后帧头里的 `targetId`
   必须真的变了,而不是"我们记了一笔账";后台 tab 不产帧,所以帧本身就是 active 的证据。
4. **没人看就不产帧。** 最后一个观看者走了,整条流停掉。
5. **键盘用带 `text` 的 `keyDown`,不是 `insertText`。** 两者都能让 `value` 变成 `hi`,
   但只有前者让页面收到真实 `keydown` —— 这一项就是
   [03 §2](../../docs/v2/works/03-input.md) 那张表。中文反过来,走 `insertText`。
6. **只读是服务端丢弃,不是前端把按钮变灰。** 只读连接照样收帧,但输入一个都不落地。
7. **光标值必须过白名单。** 远端页面不可信,`url(...)` 原样透传等于让它指使客户端
   去拉任意 URL。

## 怎么测的

**另开一条 CDP 去读远端页面的真实状态**,而不是只看自己发了什么 —— 和 demo 的
e2e 同一个姿态。"点了一下"只能证明我们发出去了,`window.clicks` 才能证明它落地。

页面用的是一个**一直在动**的 `data:` 页:screencast 只在画面变化时产帧,
拿静止页面测流会什么都收不到 —— 这本身也是被测行为之一(第 4 条)。

## 不在这测什么

- **RTT 自适应降质** —— 本机 RTT 只有几毫秒,阈值(725/600ms)永远触发不了。
  它要么单测 `view/quality.py` 的状态机,要么人为加延迟,不在这条链路上测
  ([02 §3](../../docs/v2/works/02-frame-protocol.md))。
- **tab 表本身** —— 在 [`tab_identity/`](../tab_identity/),v2 一个字段没动。
- **定位和观测** —— 在 [`pointing_at_things/`](../pointing_at_things/) 和
  [`doing_and_seeing/`](../doing_and_seeing/),它们和画面从哪来无关。
