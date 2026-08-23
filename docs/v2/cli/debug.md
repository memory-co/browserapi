# cli · 排查

```bash
webmuxd log    -t demo [-n 50] [--kind action|tab|dialog|…] [--failed] [--user WHO]
webmuxd bundle -t demo --out out.zip
```

## 1. 这两条是 agent-browser 没有的

**人和 agent 做过的事进同一条流,每条标明是谁做的**
([i §4](../works/i-agent-surface.md))。

```jsonc
{"seq":41,"kind":"action","user":"api",  "action":"click","target":{"label":"登录"},"ok":true,"ms":210}
{"seq":42,"kind":"action","user":"human","action":"pointerdown","hit":{"role":"input","name":"密码"}}
```

**这是形态那条的结构性收益,不是额外做的功能。** 把 CDP 端点直接交出去的方案
做不到:人在他们画面里点的那一下,和程序发的 `Input.dispatchMouseEvent`
**在线上是同一种字节**,无从区分。而我们的画面和输入都经过自己这一层。

对应 tmux 的 **scrollback**。`bundle` 把日志 + 每步截图打成一个 zip 带走。

## 2. 缺的那些

🔲 **`console` / `errors`。** agent-browser 有 `console [--json] [--clear]`
和 `errors`。我们**一条都没有** —— 页面里的 `console.log` 和未捕获异常
现在完全看不见。

> 后端要加的:`Runtime.consoleAPICalled` 和 `Runtime.exceptionThrown` 两个事件,
> 存进那条流。**而 `Runtime` 域现在已经是开着的了**
> ([sidecar.enable](../../../webmuxd/sidecar.py))—— 那是刚补上的,
> 之前没开,所以连接都接不上。
>
> 这一条**优先级最高**:调 agent 的时候"页面报了什么错"是第一手信息,
> 而今天要靠 `send` 里塞 js 去翻。

🔲 **`network requests` / `network route` / `har`。** 后端有
`Network.responseReceived` / `loadingFinished`(DOM 那条画面在用它抓资源),
但没有做成可查询的表,也没有拦截和改写。

🔲 **`trace`。** [c §16](../works/c-view.md) 记着 Playwright trace 能当**产物**
(实测导出的 trace 用官方 viewer 打得开),但没做成命令。

🔲 **`a11y`(axe-core 审计)/ `profiler` / `vitals` / `react`。**
这些是 agent-browser 面向"前端开发"的一半,我们面向的是"驱动一个浏览器"。
**不是不能做,是要先说清楚这个项目要不要长成那样。**

🔲 **`highlight <sel>` / `inspect`。** `inspect` 打开 DevTools ——
我们的画面是自己产的,DevTools 窗口会出现在被观看的那个浏览器里,
**观看的人会看到它** —— 和[标注层那条](../issues/标注层会被人看见.md)是同一类问题。
