# v2 · cli

**命令行是这个项目的主要使用面。** 不是"顺带给个 CLI" ——
`webmuxd server start / new / goto / click` 就是我们自己测这套东西的方式
([tests/v2_cli_simple](../../../tests/v2_cli_simple/)),也是 agent 最省事的接法。

## 三条对齐

这三条各管一层,互不打架 —— **拿不准的时候按这个顺序问**:

| 对齐谁 | 管什么 | 一句话 |
| --- | --- | --- |
| **tmux + ttyd** | **架构形态** | 一个 server 持有全部 session;`start` / `ls` / `attach` / `server stop` |
| **[agent-browser](https://github.com/vercel-labs/agent-browser)** | **命令词汇** | 同一件事就用同一个词、同样的参数位置;别自创方言 |
| **普通浏览器** | **用户体感** | 地址栏、后退、标签页 —— 人不该为了用它去学新概念 |

**冲突时谁赢:** 形态 > 词汇 > 体感。
比如 agent-browser 的 `open` 会**顺手起浏览器**,我们不这么做 ——
起会话是 `new`,那是 tmux 那一层的事;`goto` 只管导航。
**一个命令一件事,是这三条里最上面那条要的。**

## 全表

✅ 有 · ⚠️ 有但不一样 · 🔲 **待讨论**(后端还没有对应的东西)

### 会话与服务 —— [server.md](server.md)

| 我们 | agent-browser | |
| --- | --- | --- |
| `server start --port` | (daemon 自启) | ⚠️ **我们要显式起**:tmux 用 socket 没端口要挑,我们有 |
| `server stop` / `server restart` | `close` / (idle 超时) | ⚠️ **只有这三个收进二级**,理由见 [server.md §0](server.md) |
| `new --id` | `--session <name>` | ⚠️ 会话是**一等命令**,不是一个全局 flag |
| `ls` | `session list` | ✅ |
| `attach` | `dashboard start` | ⚠️ 我们的画面口本来就在,`attach` 只是打开它 |
| `kill -t` / `server stop` | `close` / (idle 超时) | ✅ |
| `has -t` | — | ✅ 只回退出码,给脚本用 |
| `info` / `install` | `doctor` / `install` | ✅ |

### 标签页 —— [tabs.md](tabs.md)

| 我们 | agent-browser | |
| --- | --- | --- |
| `tabs` | `tab` | ✅ |
| `new-tab -u` | `tab new [url]` | ✅ |
| `select-tab -t s:2` | `tab <tN\|label>` | ✅ 我们靠 `-t session:tab` 一个语法统一寻址 |
| `kill-tab` | `tab close` | ✅ |
| — | `window new` | 🔲 没有窗口这个概念 |
| — | `frame <sel>` | 🔲 **跨 iframe 还只能用 `send` 里的 js** |

### 导航 —— [navigate.md](navigate.md)

`goto` `back` `forward` `reload` `stop` `url` `wait` —— ✅ 一一对得上。
`pushstate` 🔲。

### 操作 —— [act.md](act.md)

`click` `type` `key` `scroll` `send` ✅,五种定位含 `@e1`;
`fill` `select` `check` `upload` `hover` `drag` `dblclick` ⚠️ **后端有动词,CLI 没暴露**;
`dialog --dismiss/--text` ✅ 对上 `dialog accept|dismiss`;
`mouse move/down/up/wheel` 🔲 —— 观看端那条通道有,CLI 没有。

### 读 —— [read.md](read.md)

`capture`(正文 / 截图)`status` ✅;
`snapshot -i -s --viewport --max`(带 `@e1` 的元素表)✅ ——
**号只增不重用**,这一条我们和 agent-browser 不一样,理由见那一篇;
`get text|html|value|attr|count|box|url|title` ✅、
`is visible|enabled|checked` ✅(**答案在退出码里**)——
**它们不是锦上添花**:没有它们的时候"确认一个值"只能把整页再抓一遍,
而抓整页会发号([issue](../issues/每次确认都要抓一整页-于是号在膨胀.md));
`get styles` / `get cdp-url` 🔲。

### 排查 —— [debug.md](debug.md)

`log` `bundle` ✅ —— **这两条是 agent-browser 没有的**:
人和 agent 进同一条流,每条标明是谁做的([i](../works/i-agent-surface.md))。
`console` `errors` `network` `trace` `a11y` 🔲。

### 还没碰的 —— [later.md](later.md)

`cookies` `storage` `state` `set viewport/device/geo/media`
`diff` `clipboard` `profiler` `mcp` `chat` `plugin` —— 全部 🔲,
那一篇写清楚**每一条缺的是后端的什么**。

## 全局参数

```
-t, --target session[:tab]     哪个 session、哪个 tab
-L, --socket-name NAME         换一套独立的 server(同 tmux -L)
-H, --host URL                 连远端的 server
    --json                     吐 API 的原始响应
    --user NAME                这一步的署名,进日志
    --note TEXT                这一步的思考,进日志
```

**`--user` / `--note` 是 agent-browser 没有的**,而它们是[行为流](../works/i-agent-surface.md)
的一半:一条记录不说清"谁做的、为什么",回看时就只是一串点击。

## 退出码是契约

**给脚本用的是它,不是输出。**

| 码 | 错误码 | 什么时候 |
| --- | --- | --- |
| 2 | `bad_request` `blocked_url` | 参数不对,或那个地址不许去 |
| 3 | `session_not_found` `tab_gone` `session_exists` | **寻址落空** —— 没有那个 session/tab,或那个 id 已经被占了 |
| 4 | `not_found` `not_clickable` | 找不到那个元素 / 点不了 |
| 5 | `timeout` | 超时 |
| 6 | `busy` `busy_human` | 有动作在跑,或**人正在操作** |
| 7 | `chrome_gone` `session_dead` `runtime_unavailable` `port_in_use` | 环境不行:浏览器没了、runtime 起不来、端口被占 |
| 8 | `nav_failed` | **那一页打不开** —— 改地址、换 https、看网络。和 4(改定位)是两条路 |

**4 / 5 / 6 可以重试,7 该告警。** 表在
[`cli.py` 的 `EXIT`](../../../webmuxd/cli.py) —— 那是唯一的一份。

```bash
webmuxd has -t work || webmuxd new --id work
```
