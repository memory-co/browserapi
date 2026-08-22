# v2_browser_modes —— 换画面,而且换得回来

## 为什么有这一条

**它是被一个 bug 逼出来的。**

`VNC → JPG → VNC` 切不回去:第二次点 VNC 按钮,画面纹丝不动 ——
**没有报错,console 也是干净的**,看上去像"卡住了"。

原因在 [`session-view.ts`](../../webmuxjs/client/src/viewer/session-view.ts):
"显示哪个元素"那三行只写在 `startXpra()` 里,而它被 `if (!xpra)` 挡着
(切走时那条连接没关)。**两件事缠在一起,就漏了一条路。**

顺带这也是 **VNC 那条腿唯一的端到端验证** ——
[`v2_cli_simple/`](../v2_cli_simple/) 走 VNC,但只验到"那条通道接得上";
**xpra 的像素到底有没有画到 canvas 上**,要一个真浏览器才判得了。

## 它做什么

```
webmuxd new --id demo --transport vnc
                       ↓ Playwright 打开观看页
VNC   → canvas 上有东西(不止一种颜色)、状态条说 xpra
        点一下、敲字 → 里面那个框里出现 "vnc"
JPG   → img 上有东西、尺寸和 VNC 一样(同一个 X 显示)
        点一下、敲字 → "vncjpg"
VNC   → canvas 回来了 ← **这一步曾经什么都不做**
        点一下、敲字 → "vncjpg!"
```

全程 `who.errors == []`。

## 判据:颜色,不是尺寸

`paint()` 把当值的那个画面元素画进一张离屏 canvas,采样数颜色。
**`colors <= 1` 是一整块纯色 —— 那是白屏,不是画面。**

为什么绕这一道:JPG 那条腿是 `<img>`,有 `naturalWidth` 可问;
VNC 那条是 `<canvas>`,**没有那个属性**。只判"有没有尺寸"的话,
VNC 下永远是 0,而且**一整块死白也是有尺寸的**。

## 两条想当然,都红过

- **"JPG 总是跟着人的窗口走"** —— 不对。有头这条路上浏览器跑在 xpra 的
  X 显示里,窗口是那个显示定死的,JPG 截的是同一个视口。
  跟着窗口走那条在 [`v2_browser_simple/`](../v2_browser_simple/),
  那边是无头 session。
- **"在 JS 里挑哪个元素可见"** —— `offsetParent !== null` 在 VNC 下挑中了
  那个**隐藏着的 `<img>`**,量到的是上一条腿留下的旧图。
  现在统一用 Playwright 的可见性判断:**两处各判一次,就会有一处判错。**

## 顺带量到、但没修的

**切走了那条像素通道还占着** —— 切到 JPG 之后 xpra 还在推帧,
实测 807 kbps 白花。记在
[issues/切走了那条像素通道还占着.md](../../docs/v2/issues/切走了那条像素通道还占着.md)。

**这类东西只有真浏览器量得到**:服务端那边两条通道各自都"正常工作"。

## 不在这测什么

- **DOM 模式** —— `#screen3` 是个 `<div>`,不是一张图,`paint()` 画不进
  canvas(回 `colors: -1`)。判"DOM 模式真的在放"要另一套判据,还没想清楚。
- 帧头、rencodeplus 那些线上细节 —— 在 [`pixels_from_xpra/`](../pixels_from_xpra/)

## 跑它要什么

xpra(`webmuxd install`)+ playwright。缺哪个跳哪个,不假装通过。
