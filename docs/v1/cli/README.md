# CLI

照着 tmux 设计。用过 tmux 的人应该不用查文档。

**CLI 是 lib 的一个用户**,和你的代码平级 —— 它自己不实现任何行为,
每条命令就是一次 lib 调用([`../sdk`](../sdk/)),落到线上就是一次
[`../api`](../api/) 的请求。逐行对照见 §7。

CLI 比 lib 多出来的只有三样,都是终端才需要的:

- §2 的**目标解析**(`-t work:购物车` 按标题匹配)
- §3 的**输出格式化**(`-F`、表格对齐、退出码)
- **session 的遍历和清理**(`ls` / `kill` / `info` / `kill-server`)—— lib 里没有
  `Server` 类,这类运维活就归 CLI([sdk/session.md §5](../sdk/session.md#5-lib-不管有哪些-session))

| 文件 | 内容 | 对应 |
| --- | --- | --- |
| README.md(本文) | 概念映射、`-t` 目标语法、配置、退出码 | [api/README.md](../api/README.md) |
| [tabs.md](tabs.md) | `tabs` `new-tab` `select-tab` `goto` `back` … | [api/tabs.md](../api/tabs.md) |
| [act.md](act.md) | `click` `type` `observe` `capture` `send` | [api/act.md](../api/act.md) |
| [log.md](log.md) | `log` `bundle` | [api/log.md](../api/log.md) |
| [events.md](events.md) | `watch` `log -f` | [api/events.md](../api/events.md) |
| [server.md](server.md) | `new` `ls` `attach` `share` `kill` `runtime` | [api/server.md](../api/server.md) |

## 1. 概念映射

**webmuxd ≈ tmux + ttyd,只是 pane 里渲染的不是 tty 字符,是浏览器像素。**
tmux 给多路复用与持久化,ttyd 给 web 暴露,概念见 [works/05](../works/05-server-session-runtime.md)。

| tmux | webmuxd | 实体 |
| --- | --- | --- |
| server | **server** | 按需自启,持有全部 session,见 [server.md](server.md) |
| session | **session** | 一整套 kasm + Chrome + sessiond |
| window | **tab** | 浏览器标签页,见 [tabs.md](tabs.md) |
| pane | — | 不做:一块 VNC 屏同时只显示一个 tab |
| `send-keys` | `click` / `type` / `key` / `send` | 往里面打东西,见 [act.md](act.md) |
| `capture-pane` | `capture` / `observe` | 把里面的内容抓出来 |
| scrollback | `log` | 操作日志 |
| `~/.tmux.conf` | `~/.webmuxd.conf` | 见 §5 |
| ttyd `-p` / `-b` | server `:7800` + `/s/<name>/` | 见 [server.md](server.md) |
| ttyd 默认只读 / `-W` | `share` 默认只读,`--writable` 才可写 | 见 [server.md §2](server.md#2-会话) |

## 2. 目标语法 `-t`

和 tmux 一样:`session[:tab]`

```
-t work            会话 work 的当前 tab
-t work:2          第 2 个 tab(按 index)
-t work:t_7        指定 tab id
-t work:购物车     按标题匹配(唯一匹配才行,否则报错列出候选)
```

省略 `-t` 时:用环境变量 `WEBMUXD_TARGET`,再没有就用**唯一**的那个会话;
有多个会话又没指定,报错(不猜)。这条和 tmux 略有不同——tmux 会挑最近的,
webmuxd 不猜,因为点错浏览器的代价比敲错终端大。

**目标解析全在客户端做**:`work:购物车` 先 `GET /api/tabs`,再本地按标题匹配,
匹配不唯一就退出码 2 并列出候选。服务端只认 tab id。

## 3. 全局选项

任何命令都能加:

| 选项 | 作用 |
| --- | --- |
| `-t TARGET` | 目标,见 §2 |
| `--json` | 输出 API 的**原始响应**,不做格式化 —— 方便和 API 混着用 |
| `-F FORMAT` | 自定义输出模板,占位符见 [tabs.md §2](tabs.md#2-列出) |
| `--note "..."` | 写进操作日志,对应 API 的 `note`,见 [act.md §3](act.md#3-note-参数) |
| `--user NAME` | 操作的署名,进日志。默认 `WEBMUXD_USER`,再没有就是 `cli` |
| `-L NAME` / `-S PATH` | 换 socket,语义同 tmux,见 [server.md §4](server.md#4-socket) |
| `-H URL` | 指向远端 server,见 [server.md §6](server.md#6-远端) |

`--json` 是 CLI 和 API 之间的逃生舱:

```bash
webmuxd observe -t work --json | jq '.elements[] | select(.role=="button")'
```

## 4. 命令总表

```
会话   new  ls  attach  share  kill  rename  has          → server.md
server start-server  kill-server  server  info            → server.md
tab    new-tab  tabs  select-tab  kill-tab  move-tab
       goto  back  forward  reload                        → tabs.md
操作   click  type  key  scroll  wait  send               → act.md
看     capture  observe  url  status                      → act.md
日志   log  bundle                                        → log.md
流     watch  log -f                                      → events.md
```

## 5. 配置

`~/.webmuxd.conf`,tmux 的 `set -g` 写法:

```conf
set -g image        webmuxd/operator:1.0
set -g port-base    7900
set -g viewport     1280x800
set -g log-limit    500
set -g human-yield  3000
set -g runtime      container
set -g attach-cmd   "firefox %u"      # %u = 观看 URL
```

命令行参数 > 环境变量 > 配置文件 > 内置默认。
配置项名字和容器的 `WEBMUXD_*` 环境变量一一对应(`log-limit` ↔ `WEBMUXD_LOG_LIMIT`)。

## 6. 退出码

给脚本用,**不要靠解析输出**:

| 码 | 含义 | 对应 API 错误 |
| --- | --- | --- |
| 0 | 成功 | — |
| 1 | 一般失败 | — |
| 2 | 用法错误(参数不对、目标解析不唯一、导航到特权页面) | `bad_request` `blocked_url` |
| 3 | 会话或 tab 不存在(`has` 用这个) | `session_not_found` `tab_gone` |
| 4 | 元素找不到 / 不可点 | `not_found` `not_clickable` |
| 5 | 超时 | `timeout` |
| 6 | 忙 | `busy` `busy_human` |
| 7 | 这个 session 出事了 | `chrome_gone` `session_dead` |

4/5/6 是**可重试**的,7 该告警——和 API 的错误二分一致
([api/README §4](../api/README.md#4-错误))。

```bash
webmuxd has -t work || webmuxd new -s work

webmuxd click -t work "提交订单"
case $? in
  0) ;;
  4|5|6) sleep 2; retry ;;
  7) alert "session 挂了" ;;
esac
```

## 7. ↔ API 对照

| CLI | API | 详见 |
| --- | --- | --- |
| `new` | `POST /api/sessions` | [server.md](server.md) |
| `ls` | `GET /api/sessions` | [server.md](server.md) |
| `attach` | 直接打开 `/s/{name}/`(socket 已鉴权) | [server.md](server.md) |
| `share` | `POST /api/sessions/{name}/live-token` | [server.md](server.md) |
| `kill` | `DELETE /api/sessions/{name}` | [server.md](server.md) |
| `rename` | `POST /api/sessions/{name}/rename` | [server.md](server.md) |
| `has` | `GET /api/sessions/{name}` | [server.md](server.md) |
| `info` | `GET /api/server` | [server.md](server.md) |
| `kill-server` | `POST /api/server/shutdown` | [server.md](server.md) |
| `tabs` | `GET /api/tabs` | [tabs.md](tabs.md) |
| `new-tab` | `POST /api/tabs` | [tabs.md](tabs.md) |
| `select-tab` | `POST /api/tabs/{id}/activate` | [tabs.md](tabs.md) |
| `kill-tab` | `DELETE /api/tabs/{id}` | [tabs.md](tabs.md) |
| `move-tab` | `POST /api/tabs/reorder` | [tabs.md](tabs.md) |
| `goto` `back` `forward` `reload` | `POST /api/tabs/{id}/...` | [tabs.md](tabs.md) |
| `click` `type` `key` `scroll` `wait` `send` | `POST /api/act` | [act.md](act.md) |
| `observe` | `GET /api/observe` | [act.md](act.md) |
| `capture --text` | `GET /api/text` | [act.md](act.md) |
| `capture --shot` | `GET /api/screenshot` | [act.md](act.md) |
| `url` `status` | `GET /api/status` | [act.md](act.md) |
| `log` | `GET /api/log` | [log.md](log.md) |
| `bundle` | `GET /api/log/bundle` | [log.md](log.md) |
| `log -f` `watch` | `WS /api/events` | [events.md](events.md) |

**多出来的东西**就是开头那三样:目标解析(§2)、输出格式化(§3)、
以及 session 的遍历和清理。前两样在客户端做,不进服务端;第三样是 lib 有意不做的运维面。
