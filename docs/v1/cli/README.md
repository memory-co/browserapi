# CLI

照着 tmux 设计。用过 tmux 的人应该不用查文档。

**CLI 是 lib 的一个用户**,和你的代码平级 —— 它自己不实现任何行为,
每条命令就是一次 lib 调用([`../sdk`](../sdk/)),落到线上就是一次
[`../api`](../api/) 的请求。逐行对照见 §7。

CLI 比 lib 多出来的只有两样,都是终端才需要的:

- §2 的**目标解析**(`-t work:购物车` 按标题匹配)
- §3 的**输出格式化**(`-F`、表格对齐、退出码)

`ls` / `kill` / `info` **不是** CLI 独有的 —— lib 那边是
[`Webmuxd`](../sdk/manager.md) 上的 `sessions()` / `kill()` / `info()`。

| 文件 | 内容 | 对应 |
| --- | --- | --- |
| README.md(本文) | 概念映射、`-t` 目标语法、配置、退出码 | [api/README.md](../api/README.md) |
| [install.md](install.md) | `webmuxd install` —— 装一次,之后别再问 | —— |
| [tabs.md](tabs.md) | `tabs` `new-tab` `select-tab` `goto` `back` … | [api/tabs.md](../api/tabs.md) |
| [act.md](act.md) | `click` `type` `observe` `capture` `send` | [api/act.md](../api/act.md) |
| [log.md](log.md) | `log` `bundle` | [api/log.md](../api/log.md) |
| [server.md](server.md) | `new` `ls` `attach` `share` `kill` `runtime` | [api/server.md](../api/server.md) |

## 1. 概念映射

**webmuxd ≈ tmux + ttyd,只是 pane 里渲染的不是 tty 字符,是浏览器像素。**
tmux 给多路复用与持久化,ttyd 给 web 暴露,概念见 [works/05](../works/05-server-session-runtime.md)。

| tmux | webmuxd | 实体 |
| --- | --- | --- |
| server | **server** | 按需自启,持有全部 session,见 [server.md](server.md) |
| session | **session** | 一整套 kasm + Chromium + sessiond |
| window | **tab** | 浏览器标签页,见 [tabs.md](tabs.md) |
| pane | — | 不做:一块 VNC 屏同时只显示一个 tab |
| `send-keys` | `click` / `type` / `key` / `send` | 往里面打东西,见 [act.md](act.md) |
| `capture-pane` | `capture` / `observe` | 把里面的内容抓出来 |
| scrollback | `log` | 操作日志 |
| `~/.tmux.conf` | **不做** | 参数从 lib 传,见 §5 |
| ttyd `-p` / `-b` | server `:7800` + `/s/<id>/` | 见 [server.md](server.md) |
| ttyd 默认只读 / `-W` | `share` 默认只读,`--writable` 才可写 | 见 [server.md §2](server.md#2-会话) |

## 2. 目标语法 `-t`

和 tmux 一样:`session_id[:tab]`

```
-t work            id 为 work 的 session 的当前 tab
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
| `--user NAME` | 操作的署名,进日志。默认 `WEBMUXD_LOGIN`,再没有就是 `cli` |
| `-L NAME` / `-S PATH` | 换 socket,语义同 tmux,见 [server.md §4](server.md#4-socket) |
| `-H URL` | 指向远端 server,见 [server.md §6](server.md#6-远端) |

`--json` 是 CLI 和 API 之间的逃生舱:

```bash
webmuxd observe -t work --json | jq '.elements[] | select(.role=="button")'
```

## 4. 命令总表

```
装     install                                          → install.md
会话   new  ls  attach  share  kill  rename  has          → server.md
server start-server  kill-server  server  info            → server.md
tab    new-tab  tabs  select-tab  kill-tab  move-tab
       goto  back  forward  reload  stop  dialog          → tabs.md
操作   click  type  key  scroll  wait  send               → act.md
看     capture  observe  url  status                      → act.md
日志   log  bundle                                        → log.md
流     log -f                                          → log.md
```

## 5. 没有配置文件

**`webmuxd` 不读 `~/.webmuxd.conf`,也不读任何配置文件。**

参数从 **lib** 传([sdk/manager.md §1](../sdk/manager.md#1-session--拿一个-session)):

```python
web.session(id="work", api_port=7900, view_port=6901,
            runtime="process", window_size="1024x768")
```

CLI 只是把同一批参数摆成 flag。**这是 lib 是主体的直接后果** ——
配置文件会变成第二种说同一件事的方式,而两种说法迟早会不一致。

而且用户就开一个浏览器,`--runtime process` 打一次的成本远低于
"我上次在配置里写了什么来着"。

| | |
| --- | --- |
| 一次性的参数 | 命令行 flag / `session(...)` 的入参 |
| 部署环境给的 | `WEBMUXD_*` 环境变量(容器那几个,见 [works/01 §2](../works/01-container.md#2-起容器)) |
| 探出来的事实 | `~/.webmuxd.json`,`webmuxd install` 写,**别手写**([install.md](install.md)) |

优先级只有三档:**命令行 > 环境变量 > 内置默认。**

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
| `attach` | 直接打开 `/s/{name}/vnc/`(socket 已鉴权) | [server.md](server.md) |
| `share` | `POST /api/sessions/{id}/live-token` | [server.md](server.md) |
| `kill` | `DELETE /api/sessions/{name}` | [server.md](server.md) |
| `rename` | `POST /api/sessions/{name}/rename` | [server.md](server.md) |
| `has` | `GET /api/sessions/{name}` | [server.md](server.md) |
| `install` | 不打接口 —— 本机探测,写 `~/.webmuxd.json` | [install.md](install.md) |
| `info` | `GET /api/server` | [server.md](server.md) |
| `kill-server` | `POST /api/server/shutdown` | [server.md](server.md) |
| `tabs` | `GET /api/tabs` | [tabs.md](tabs.md) |
| `new-tab` | `POST /api/tabs` | [tabs.md](tabs.md) |
| `select-tab` | `POST /api/tabs/{id}/activate` | [tabs.md](tabs.md) |
| `kill-tab` | `DELETE /api/tabs/{id}` | [tabs.md](tabs.md) |
| `move-tab` | `POST /api/tabs/reorder` | [tabs.md](tabs.md) |
| `goto` `back` `forward` `reload` `stop` | `POST /api/tabs/{id}/...` | [tabs.md](tabs.md) |
| `dialog` | `POST /api/tabs/{id}/dialog` | [tabs.md](tabs.md) |
| `click` `type` `key` `scroll` `wait` `send` | `POST /api/act` | [act.md](act.md) |
| `observe` | `GET /api/observe` | [act.md](act.md) |
| `capture --text` | `GET /api/text` | [act.md](act.md) |
| `capture --shot` | `GET /api/screenshot` | [act.md](act.md) |
| `url` `status` | `GET /api/status` | [act.md](act.md) |
| `log` | `GET /api/log` | [log.md](log.md) |
| `bundle` | `GET /api/log/bundle` | [log.md](log.md) |
| `log -f` | 跟着日志滚 | [log.md](log.md) |

**多出来的东西**就是开头那两样:目标解析(§2)和输出格式化(§3)。
都在客户端做,不进服务端。
