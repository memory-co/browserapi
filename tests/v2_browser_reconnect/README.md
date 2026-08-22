# v2_browser_reconnect —— 网抖一下,画面回不回得来

**最终用户最常撞的一类**:笔记本合盖、切了个 WiFi、地铁进隧道 ——
回来之后画面是继续动,还是永远停在那一帧。

## 它挖出来的

两条通道**一条会重连一条不会**:

| | 断了之后 |
| --- | --- |
| `/channel/cdp` | 1 秒后自己爬回来([`channel/cdp.ts`](../../webmuxjs/client/src/channel/cdp.ts)) |
| `/channel/xpra` | **报个 `closed` 就完了** |

而**代码里没有一句话说这是有意的** —— 是漏了。表现:VNC 下网抖一次,
画面永远停在最后一帧,只能刷新页面。

顺带还有一处:`dead` 那个灰掉画面的类**加上去就再没摘过** ——
加上重连之后,画面回来了人看到的还是一块灰的。
**好起来了要说,不只是坏了要说。**

## 怎么把网掐了

**Chromium 自己的断网模拟对 loopback 上已经建好的 WebSocket 一律无效。**
两个都试过:

- `context.set_offline(True)` —— 状态一直是「已连接」
- CDP `Network.emulateNetworkConditions {offline: true}` —— 同上

用的是 Playwright 的 `route_web_socket`:把那几条通道从中间接过来,
测试里说掐就掐。副产品是 `who.channels` —— **每重连一次就多一条**,
数它就知道断没断过。

## 判据:新帧在流,不是画面上有东西

断线前那一帧还留在画布上,**颜色数一模一样**。
所以恢复之后让里面换一页(`webmuxd goto`),
再看画面的采样指纹变不变 —— 变了才算"还在流"。

```python
was = who.paint()["sig"]
cli.run("goto", "-t", sid, ELSE)
who.wait_fresh(was)          # ← 判据
```

## 不在这测什么

- **弱网(慢,不是断)** —— `route_web_socket` 也能拖慢/丢包,还没写。
  画质自适应那套([c1](../../docs/v2/works/c1-quality.md))就该在那儿验。
- **server 重启** —— 那是另一回事:session 也没了,人该看到的是
  "这个 session 不在了",不是"重连中"。
- **断线期间人点的那些** —— 该丢还是该补?**还没想清楚**,所以没写断言。

## 跑它要什么

playwright(两条都要)+ xpra(只有 VNC 那条要)。缺哪个跳哪个。
