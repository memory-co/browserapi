# cli · 标签页

**这一层照普通浏览器。** 人对"标签页"已经有完整的直觉,不该为了用它学新词。

```bash
webmuxd tabs       -t demo [--format TPL]
webmuxd new-tab    -t demo [-u URL] [--no-switch]
webmuxd select-tab -t demo:2
webmuxd kill-tab   -t demo:2
```

## 1. tab 是 tmux 的 window

| tmux | 浏览器 | 我们 |
| --- | --- | --- |
| `list-windows` | 标签栏 | `tabs` |
| `new-window` | ⌘T | `new-tab` |
| `select-window` | 点一下 | `select-tab` |
| `kill-window` | ⌘W | `kill-tab` |

`t_N` 是**我们自己分配的,关掉不复用** —— CDP 的 targetId 一重启就全变,
而日志里那个 `t_7` 必须永远指同一个东西([f](../works/f-tabs.md))。

## 2. `active` 就是"浏览器现在放在前台的那一页"

CDP 没有"tab 被激活了"这种事件,但**页面自己知道**
(`document.visibilityState`)。所以它是**观测出来的**,不是我们记的账 ——
`select-tab` 只是发个信号,**等那一页报回来才算切完**,
所以它返回的时候那件事已经真的成立了([f §3](../works/f-tabs.md))。

> 0.18.0 之前是反过来的:我们记一本账再去同步。那本账有一个没写出来的前提
> ——"只有我们会动前台"—— 而页面 `target=_blank` 开出来的 tab,
> Chromium 直接就把前台切走了。结果是画面上一页、tab 条另一页,**不报错**。

**不带下标的命令落在"屏幕上那一页"。** 人点了个 `target=_blank`,
前台跟着换,下一条不带下标的命令也跟着换 —— 要确定性就带下标(`-t nt:0`)。

**要像素就得在前台**:`capture --shot` 指向非激活 tab 时会先切过去(画面会跳),
纯输入的 `click` / `type` 不用切。

## 3. 和 agent-browser 的差别

| | agent-browser | 我们 |
| --- | --- | --- |
| 列 | `tab` | `tabs` ⚠️ 复数,和 `tab new` 那种子命令风格不同 |
| 新建 | `tab new [url]` | `new-tab -u URL` |
| 切换 | `tab <tN\|label>` | `select-tab -t demo:2` |
| 标签名 | `tab new --label docs` | 🔲 **待讨论** |

> **`--label` 值得抄。** agent-browser 允许给 tab 起名字然后 `tab docs` 切过去。
> 我们今天靠 `-t demo:购物车` 按**标题**匹配 —— 标题是页面给的,会变。
> 后端要加的是 tab 表上一个用户可写的 `label` 字段([`models.TabInfo`](../../../webmuxd/models.py))。

🔲 **待讨论:`window new`。** 我们没有窗口这个概念 —— 一个 session 一个浏览器、
一个窗口。要不要多窗口,取决于有没有人真的需要"两个窗口并排"。

🔲 **待讨论:`frame <sel>` / `frame main`。** 跨 iframe 今天只能钻进
`send` 里写 js。而[动词表那一篇](../works/i-agent-surface.md#21-还缺的动词)
已经把 `switch_frame` 列成缺的了 —— **后端先有,CLI 再谈**。

## 🔲 待讨论:`wait` 等不了 tab

`wait` 等得了页面上的文字、元素、地址,**等不了"又开了一个 tab"**。
而页面自己开的 tab 是异步冒出来的 —— 点完一个 `target=_blank` 的链接立刻问
`tabs`,有时快了一步。

今天只能轮询([`tests/v2kit.py`](../../../tests/v2kit.py) 的 `wait_tabs`
就是这么顶的)。该长成 `webmuxd wait -t demo --tabs 2`,
或者更贴切的 `--new-tab`。

后端**有**这个事件(`tab.created` 走 `/api/events`),缺的只是把它接到 `wait` 上。
