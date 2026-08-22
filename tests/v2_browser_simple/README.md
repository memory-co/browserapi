# v2_browser_simple —— 一个真人打开观看页,他会撞上什么

前面那几条都是**我们自己发命令、我们自己读结果**。中间那一段 ——
**人在画面上点的那一下,到底有没有到里面** —— 一条都没验过。

这一条补的就是那一段。设计在
[works/test.md §5](../../docs/v2/works/test.md)。

## 形状:一个 session,加一个真的浏览器

```
webmuxd new    --id demo               ← 只有这一个 session
webmuxd goto   -t demo baidu
webmuxd attach -t demo --print-only    → http://127.0.0.1:P/s/demo/
                                          ↓ Playwright 起一个真浏览器打开它
                                       who.click(搜索框)
                                       who.type("web")
                                       who.resize(900, 700)
webmuxd snapshot -t demo -i            ← 判据:里面那个框里出现了 "web"
webmuxd log      -t demo --user human  ← 判据:那一下记的是 human,还记了点中哪个控件
```

## 为什么不是又一个 webmuxd session

**试过,不对。** 三条理由:

1. **用自己的栈去测自己的栈是循环的** —— 截屏那条腿坏了,
   "被观看的"和"观看的"会一起坏,而测试照样绿。
2. 要测的是**最终用户会撞上什么**,那第二个浏览器就得是**用户那种浏览器**,
   不是我们栈里的另一个 headless session。
3. 用户那边最要紧的一类信息 —— **观看页自己报的错** —— 我们的 CLI
   今天根本读不到(`console` 在 [cli/debug.md](../../docs/v2/cli/debug.md)
   里还是 🔲)。Playwright 一行 `page.on("pageerror")` 就有了。

那条"不引入第二套工具"的洁癖是错的:它把**"我们的工具好不好用"**
和**"用户会不会出问题"**混成了一件事,而这一条测的是后者。

## 它盯着什么(按重要性)

1. **人点下去,里面真的动了。** 那一下要穿过:真浏览器的 DOM 事件 → 归一化
   → 上行消息 → 服务端翻译成 `Input.*` → 那个 Chromium。
   **中间任何一环断了,这一下什么都不会发生,而且不报错。**
2. **行为流里记的是 `human`,不是 `cli`。**
   这是把 CDP 端点直接交出去的方案**做不到**的事 —— 人点的那一下和程序发的
   `Input.dispatchMouseEvent` 在线上是同一种字节。
3. **观看页一条错都没报。** 用户说"打开是白屏"时这是第一手信息,
   **而只有真浏览器验得了。**
4. **像素真的落地了** —— `<img>` 的 `naturalWidth` 不是 0,
   而且和状态条上那行「帧 W×H」对得上。
5. **窗口一改,里面跟着变** —— 分辨率跟着观看的人走,不是写死的。
   这是"用起来像个普通浏览器"里最容易坏的一条。
6. **光标跟着手走** —— 移到搜索框上是 I 型,移开变回箭头。
   读的是 `screenEl.style.cursor`,**不是那条协议消息** ——
   「我们发了什么」和「人看到了什么」是两件事,这一面只认后者。
7. **读屏的人找得到那块画面** —— `get_by_role("img", name="浏览器画面")`。

## 两个坑,都是"两件事被当成一件"

- **「已连接」不等于「画出来了」。** WS 接上之后服务端才开始
  `startScreencast`,第一帧还要走一个来回。所以 `wait_connected()`
  和 `wait_painted()` 是两个方法 —— 第一版只等前者,一跑就红。
- **敲字之前必须先点一下。** 观看端在 `mousedown` 时才把焦点交给隐藏的
  textarea(IME 要它)。**这两步的顺序是有意义的,不是凑的。**

## 不在这测什么

- 帧头、ack 环那些线上细节 —— 在 [`pixels_on_a_wire/`](../pixels_on_a_wire/)
- 定位规则本身 —— 在 [`pointing_at_things/`](../pointing_at_things/)
- **VNC 那条腿** —— 这一条走 JPG,判据是 `<img>` 的 `naturalWidth`。
  VNC 下像素画进 `<canvas>`,没有那个属性,要读画布像素才判得了
  ([works/test.md §5.5](../../docs/v2/works/test.md))
- **只读连接点不动** —— 想验,但**今天从 CLI 够不着**:
  只读 token 要 `POST /api/live-token`,那个口子还没做
- **弱网、断线重连** —— Playwright 做得到(`route` 拦流量、断 WS),
  还没写。"网抖一下画面回不来"是用户最常撞的一类

## 跑它要什么

```bash
pip install playwright && playwright install chromium
```

没装就跳过,不假装通过。
