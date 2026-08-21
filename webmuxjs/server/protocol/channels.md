# 四条 WS 通道

| 路径 | 方向 | 传什么 |
| --- | --- | --- |
| `/channel/cdp` | **双向** | JPG 帧(二进制,28 字节头)+ 下行 JSON;**所有输入从这条上去** |
| `/channel/xpra` | 双向 | xpra 协议裸包(8 字节头 + rencodeplus) |
| `/channel/rrweb` | **只下行** | rrweb 事件,`{type: "dom", e: "<JSON 字符串>"}` |
| `/api/events` | 只下行 | tab 变化、对话框、下载 |

认证:`?t=<token>` 查询串。token 会进历史和 Referer,
所以页面一拿到就 `history.replaceState` 抹掉。

## `/channel/rrweb` 为什么只下行

**结构上没有上行,不是"发之前判断一下"。**
服务端那个 handler 里根本没有接收端;客户端这一侧用同样的方式守 ——
[`client/src/channel/rrweb.ts`](../../client/src/channel/rrweb.ts) 里**没有发送函数**。

这条是"DOM 画面是只读的"那个保证的落点:重放出来的 DOM 整个
`pointer-events: none`,事件全落在容器上,再走 `/channel/cdp` 翻译成 `Input.*`。

## 断了会怎样

- `/channel/cdp` 断 → 画面停 + **输入送不出去**,重连
- `/channel/xpra` 断 → 同上,但只影响 VNC 那条
- `/channel/rrweb` 断 → **画面停,输入照常送达** —— 所以只重连,
  不把整个会话判成不可用
- `/api/events` 断 → tab 条不再自动更新,重连

## ack 那条环

**两个环,别混。**

- **环 A**:服务端收到 `Page.screencastFrame` → 立刻
  `Page.screencastFrameAck`。**无条件,和客户端没关系** —— 不回就停流
- **环 B**:客户端收到一帧 → 立刻发 `ack`。这是背压,也是 RTT 探针

客户端那侧三条:**立即发、带帧号、不搭车**;
另外每收一帧重置一个 **3 秒心跳** —— 某一帧丢在路上的话,
客户端永远等不到、也就永远不 ack,服务端额度耗尽就是永久卡死,
补一发就自愈。
