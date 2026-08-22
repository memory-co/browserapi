# v2 · cli

**先起 server,再加 session** —— 和 tmux 一样,一个 server 装着全部 session。

```console
$ webmuxd install                        # 一次性:探、下、写记录
$ webmuxd start --port 7900
server  →  http://127.0.0.1:7900/   (还没有 session:webmuxd new --id demo)

$ webmuxd new --id demo
demo  →  http://127.0.0.1:7900/s/demo/

$ webmuxd ls
demo       process   VNC   1 个 tab   http://127.0.0.1:7900/s/demo/
```

> **相对 [v1/cli](../../v1/cli/) 变了三处**,其余(tab、动作、日志那些命令)
> 一个字没动,仍以 v1 那份为准:
>
> 1. **`start` 是新的,`new` 不再要 `--port`**(§1)
> 2. **`capture` 就是"读"的全部**,`observe` 没有了(§3)
> 3. **`kill-server`** 停 server 和全部 session(§1)

## 1. server 与 session

```bash
webmuxd start   --port 7900 [--bind 127.0.0.1]
webmuxd new     --id demo [--transport vnc|jpg|dom] [--url URL] [--browser PATH]
webmuxd ls
webmuxd attach  -t demo [-p]
webmuxd has     -t demo
webmuxd kill    -t demo
webmuxd kill-server
```

**`start` 是显式的,不按需自启。** tmux 能自启是因为它用 socket,
没有端口要挑;我们有,而那条规矩是「端口由你给」
([h §6](../works/h-runtime.md#6-端口由你给))。没起 server 时:

```console
$ webmuxd new --id demo
✗ session_not_found: 没有在跑的 server —— 先 `webmuxd start --port 7900`
```

`-L name` / `-S path` 照抄 tmux:**换 socket = 换一套独立的 server**。
登记的只剩一行"server 在哪个口上" —— 以前那是一张 session 表,
因为没有常驻进程,**那个文件在冒充 server**。

**`--bind 0.0.0.0` 只在 `start` 上说一次**(以前每个 session 各绑各的),
而且会打印一行警告:对外开放是你的决定,但不能悄悄发生。

## 2. 退出码是给脚本的契约

**不要靠解析输出。**

| 码 | 什么时候 |
| --- | --- |
| 2 | 参数不对 / 端口被占或要 root |
| 3 | 没有那个 session,或没有在跑的 server |
| 4 | 找不到那个元素 / 点不了 |
| 5 | 超时 |
| 6 | 有动作在跑 / 人正在操作 |
| 7 | 浏览器起不来 / runtime 不可用 |

```bash
webmuxd has -t work || webmuxd new --id work
```

## 3. 读:`capture` 就是全部

```console
$ webmuxd capture -t demo             # 正文,对应 tmux capture-pane -p
$ webmuxd capture -t demo --shot p.webp   # 那一刻的页面
```

**没有"列元素"这个命令。** `webmuxd observe` 砍了 ——
元素表只服务定位(`webmuxd click -t demo "提交订单"`),不单独开口子
([i §3](../works/i-agent-surface.md#3-读的那一面一张图和正文))。

## 4. 其余命令没变

tab(`tabs` / `new-tab` / `select-tab` / `kill-tab` / `goto` / `back` …)、
动作(`click` / `type` / `key` / `scroll` / `wait` / `send`)、
日志(`log` / `bundle`)、`install` / `info` —— 一律见 [v1/cli](../../v1/cli/)。

## 5. ↔ 别处

| | |
| --- | --- |
| tab / 动作 / 日志那些命令 | [v1/cli](../../v1/cli/) —— 那部分没变 |
| Python 那一面 | [sdk](../sdk/) |
| HTTP 那一面 | [api](../api/) |
| 为什么先 start 再 new | [k](../works/k-one-server.md) |
