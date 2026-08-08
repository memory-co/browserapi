# CLI

照着 tmux 设计。用过 tmux 的人应该不用查文档。

## 1. 概念映射

**webmuxd ≈ tmux + ttyd,只是 pane 里渲染的不是 tty 字符,是浏览器像素。**
tmux 给多路复用与持久化,ttyd 给 web 暴露,概念见 [works/05](../works/05-server-session-runtime.md)。

| tmux | webmuxd | 实体 |
| --- | --- | --- |
| server | **server** | 按需自启,持有全部 session,见 §7 |
| session | **session** | 一整套 kasm + Chrome + sessiond |
| window | **tab** | 浏览器标签页 |
| pane | — | 不做:一块 VNC 屏同时只显示一个 tab |
| `send-keys` | `click` / `type` / `key` / `send` | 往里面打东西 |
| `capture-pane` | `capture` / `observe` | 把里面的内容抓出来 |
| scrollback | `log` | 操作日志 |
| `~/.tmux.conf` | `~/.webmuxd.conf` | |
| ttyd `-p` / `-b` | server `:7800` + `/s/<name>/` | 见 §7 |
| ttyd 默认只读 / `-W` | `share` 默认只读,`--writable` 才可写 | 见 §3 |

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

## 3. 会话

```bash
webmuxd new [-s NAME] [--runtime R] [-p PORT] [-u URL] [-v WxH] [--volume VOL] [-d]
webmuxd ls
webmuxd attach -t NAME [-p]
webmuxd share  -t NAME [--writable] [--ttl 1h]
webmuxd kill -t NAME
webmuxd kill-server
webmuxd rename -t NAME NEW
webmuxd has -t NAME
```

```console
$ webmuxd new -s work
work  →  http://localhost:7900

$ webmuxd new -s scrape -u https://example.com
scrape  →  http://localhost:7901

$ webmuxd ls
work    container  7900  3 tabs  shop.example.com/cart   ●
dev     process    7901  1 tab   localhost:3000
prod    remote     -     5 tabs  intranet.corp/dash
stale   process    7903  dead — webmuxd kill -t stale 清掉

$ webmuxd attach -t work        # 自己看,完整权限,用默认浏览器打开
$ webmuxd attach -t work -p     # 只打印 URL,不开浏览器(无 GUI 环境用)
http://localhost:7800/s/work/

$ webmuxd share -t work         # 给别人的链接,默认只读(抄 ttyd)
http://localhost:7800/s/work/?t=...   (只读,1 小时后过期)

$ webmuxd share -t work --writable
http://localhost:7800/s/work/?t=...   (可操作,1 小时后过期)
⚠ 这个链接能操作你的浏览器,包括已登录的站点
```

- `-p PORT` 不给就自动从 7900 往上找空闲端口
- `-d` 建完不 attach(默认就是不 attach,`-d` 只是为了跟 tmux 的手感一致)
- **detach 不需要命令**——关掉网页就是 detach,容器照跑
- `has` 只返回退出码,给脚本用:`webmuxd has -t work || webmuxd new -s work`
- `attach` 是**你自己看**,走 socket 鉴权,完整权限
- `share` 是**给别人**,签一次性 token。**默认只读**,和 ttyd 的默认一致;
  要可操作得显式 `--writable`,并且会打印一行警告
- `kill-server` 停掉 server。**`process` 的 session 跟着死,`container` 的活着**,见 §7

## 4. tab

```bash
webmuxd new-tab    -t NAME [-u URL] [-n]      # -n = 建完不切过去
webmuxd tabs       -t NAME [-F FORMAT]
webmuxd select-tab -t NAME:2
webmuxd kill-tab   -t NAME:2
webmuxd move-tab   -t NAME:2 --to 0
webmuxd goto       -t NAME URL
webmuxd back       -t NAME
webmuxd forward    -t NAME
webmuxd reload     -t NAME
```

```console
$ webmuxd tabs -t work
0: 购物车        shop.example.com/cart      ●
1: 订单确认      shop.example.com/order/91
2: 帮助中心      help.example.com

$ webmuxd tabs -t work -F '#{tab_id} #{tab_url}'
t_3 https://shop.example.com/cart
t_7 https://shop.example.com/order/91
t_9 https://help.example.com
```

`-F` 的占位符和 tmux 同款写法:
`#{tab_id}` `#{tab_index}` `#{tab_title}` `#{tab_url}` `#{tab_active}` `#{tab_loading}`
`#{session_name}` `#{session_port}` `#{tab_count}`

## 5. 操作

```bash
webmuxd click   -t NAME "登录"
webmuxd click   -t NAME --role button --name 登录
webmuxd type    -t NAME --label 手机号 13800000000
webmuxd key     -t NAME Enter
webmuxd scroll  -t NAME --dy 400
webmuxd wait    -t NAME --text "订单已提交" [--timeout 10]
webmuxd send    -t NAME '<json>'          # 原始动作数组,对应 tmux send-keys
```

```console
$ webmuxd click -t work "提交订单"
✓ click → button "提交订单"  412ms
  → /order/9182   出现『订单已提交』

$ webmuxd click -t work "提交"
✗ not_found: 找不到「提交」
  候选:  button "提交订单"
         button "提交并支付"
         link   "提交反馈"
```

**定位失败会列出候选**,和 API 的 `candidates` 是同一份东西([agent.md §2](agent.md))。

`send` 是逃生舱,直接发 [agent.md §3](agent.md#3-动作表) 的动作数组,
CLI 没覆盖到的动作都能用它:

```bash
webmuxd send -t work '[{"type":"select","label":"城市","value":"上海"},
                      {"type":"click","text":"搜索"}]'
```

`--note "..."` 在任何操作命令上都能加,写进操作日志(对应 API 的 `note`):

```bash
webmuxd click -t work "提交订单" --note "购物车已确认,现在下单"
```

## 6. 看

```bash
webmuxd capture  -t NAME [--text | --shot FILE | --elements]
webmuxd observe  -t NAME [--shot FILE] [--json]
webmuxd url      -t NAME
webmuxd status   -t NAME
webmuxd log      -t NAME [-n 50] [-f] [--failed]
webmuxd watch    -t NAME [--types 'tab.*']
webmuxd bundle   -t NAME -o out.zip
```

```console
$ webmuxd url -t work
https://shop.example.com/cart

$ webmuxd capture -t work --text | head -3      # 对应 tmux capture-pane -p
购物车
共 2 件商品

$ webmuxd observe -t work                        # agent 观测,人也能看
[12] button  "提交订单"
[13] textbox "优惠码" = ""
[14] link    "返回购物车"        (需下滑)

$ webmuxd log -t work -n 3
14:22:03  💭 购物车已确认,现在下单
          click "提交订单" → button "取消订单"
          → /cancel  出现『订单已取消』
14:22:06  👤 人点了 (612,340)
14:22:09  ✗ click "确认" not_found

$ webmuxd log -t work -f                         # 跟着滚,像 tail -f
$ webmuxd watch -t work --types 'tab.*'          # 事件流
```

`log -f` 和 `watch` 都是流式,`Ctrl-C` 退出。
`--json` 在所有读命令上可用,输出就是 API 的原始响应——**方便和 API 混着用**。

## 7. server

和 tmux 一样,**按需自启,你几乎不会直接碰它**。

```bash
webmuxd start-server                      # 有这个命令,但基本用不到
webmuxd kill-server
webmuxd server --listen 0.0.0.0:7800      # 开 TCP,需要 WEBMUXD_TOKEN
webmuxd info                              # server 状态、探测到哪些 runtime
```

socket 语义和 tmux 完全一致:

```bash
webmuxd-L ci new -s build                # 换个 socket = 另一套互不可见的 server
webmuxd-S /tmp/x.sock ls
```

`kill-server` 的效果**取决于 runtime**,这点必须知道:

| session 的 runtime | `kill-server` 之后 |
| --- | --- |
| `process` | **跟着死**(是 server 的子进程,和 tmux 的 pane 一样) |
| `container` | **活着**,server 重启后自动重新接管 |
| `remote` | **活着**,本来就不归它管 |

所以 `webmuxd ls` 一定会显示 runtime 那一列 —— 不然你不知道自己的 session 抗不抗得住重启。

管理接口见 [server.md](server.md)。

## 8. runtime

session 怎么被拉起来,创建时选一次,之后所有命令都一样:

```bash
webmuxd new -s work                                     # container(默认)
webmuxd new -s dev  --runtime process                   # 不要 docker,秒起,没隔离
webmuxd new -s prod --runtime remote \
                   --endpoint https://browser.internal:7800
```

```conf
# ~/.webmuxd.conf
set -g runtime container
```

docker 不可用又没给 `--runtime` 时**报错,不静默降级**:

```console
$ webmuxd new -s work
✗ runtime_unavailable: docker 不可用
  可以改用 --runtime process,但那样没有隔离(页面跑在你自己机器上)
```

## 9. 远端

```bash
webmuxd-H https://browser.internal:7800 ls
export WEBMUXD_HOST=https://browser.internal:7800
export WEBMUXD_TOKEN=...
```

`-H` 指向的是**一个远端 server**(不是单个 session),所以 `new` / `ls` / `kill`
这些会话级命令**照常可用**——由那边的 server 执行。

这是相对早先设计的一个改进:以前 `-H` 指向单个容器,会话级命令就没法用了。

## 10. 配置

`~/.webmuxd.conf`,tmux 的 `set -g` 写法:

```conf
set -g image        webmuxd/operator:1.0
set -g port-base    7900
set -g viewport     1280x800
set -g log-limit    500
set -g human-yield  3000
set -g attach-cmd   "firefox %u"      # %u = 观看 URL
```

命令行参数 > 环境变量 > 配置文件 > 内置默认。
配置项名字和容器的 `WEBMUXD_*` 环境变量一一对应(`log-limit` ↔ `WEBMUXD_LOG_LIMIT`)。

## 11. 退出码

给脚本用,不要靠解析输出:

| 码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 一般失败 |
| 2 | 用法错误(参数不对) |
| 3 | 会话或 tab 不存在(`has` 用这个) |
| 4 | 元素找不到 / 不可点(`not_found` `not_clickable`) |
| 5 | 超时 |
| 6 | 忙(`busy` / `busy_human`) |
| 7 | 这个 session 出事了(`chrome_gone`) |

4/5/6 是**可重试**的,7 该告警——和 API 的错误二分一致([README §4](README.md#4-错误))。

## 12. CLI ↔ API 对照

CLI 不做任何 API 没有的事,每条命令就是一次调用:

| CLI | API |
| --- | --- |
| `new` | `POST /api/sessions`([server.md](server.md)) |
| `ls` | `GET /api/sessions` |
| `attach` | 直接打开 `/s/{name}/`(socket 已鉴权) |
| `share` | `POST /api/sessions/{name}/live-token` |
| `kill` | `DELETE /api/sessions/{name}` |
| `info` | `GET /api/server` |
| `kill-server` | `POST /api/server/shutdown` |
| `tabs` | `GET /api/tabs` |
| `new-tab` | `POST /api/tabs` |
| `select-tab` | `POST /api/tabs/{id}/activate` |
| `kill-tab` | `DELETE /api/tabs/{id}` |
| `move-tab` | `POST /api/tabs/reorder` |
| `goto` `back` `forward` `reload` | `POST /api/tabs/{id}/...` |
| `click` `type` `key` `scroll` `wait` `send` | `POST /api/act` |
| `observe` | `GET /api/observe` |
| `capture --text` | `GET /api/text` |
| `capture --shot` | `GET /api/screenshot` |
| `url` `status` | `GET /api/status` |
| `log` | `GET /api/log` |
| `log -f` `watch` | `WS /api/events` |
| `bundle` | `GET /api/log/bundle` |

**唯一多出来的东西**是目标解析(`work:购物车` → 先 `GET /api/tabs` 再按标题匹配)和输出格式化。
这两样都在客户端做,不进服务端。
