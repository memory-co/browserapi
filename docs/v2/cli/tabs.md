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

## 2. `active` 不是猜出来的

CDP **没有**"tab 被激活了"这种事件。所以我们记自己的账,
再用 `Target.activateTarget` 把 Chromium 拽过来对齐 —— 不是反过来。

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
