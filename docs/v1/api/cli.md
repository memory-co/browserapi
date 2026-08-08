# CLI

照着 tmux 设计。用过 tmux 的人应该不用查文档。

## 1. 概念映射

| tmux | webmux | 实体 |
| --- | --- | --- |
| server | **docker** | 不跑 webmux 自己的常驻进程,见 §7 |
| session | **session** | 一个容器 = 一个浏览器 |
| window | **tab** | 浏览器标签页 |
| pane | — | 不做。浏览器没有对应物 |
| `send-keys` | `click` / `type` / `key` / `send` | 往里面打东西 |
| `capture-pane` | `capture` / `observe` | 把里面的内容抓出来 |
| scrollback | `log` | 操作日志 |
| `~/.tmux.conf` | `~/.webmux.conf` | |

## 2. 目标语法 `-t`

和 tmux 一样:`session[:tab]`

```
-t work            会话 work 的当前 tab
-t work:2          第 2 个 tab(按 index)
-t work:t_7        指定 tab id
-t work:购物车     按标题匹配(唯一匹配才行,否则报错列出候选)
```

省略 `-t` 时:用环境变量 `WEBMUX_TARGET`,再没有就用**唯一**的那个会话;
有多个会话又没指定,报错(不猜)。这条和 tmux 略有不同——tmux 会挑最近的,
webmux 不猜,因为点错浏览器的代价比敲错终端大。

## 3. 会话

```bash
webmux new [-s NAME] [-p PORT] [-u URL] [-v WxH] [--volume VOL] [-d]
webmux ls
webmux attach -t NAME [-p] [--read-only]
webmux kill -t NAME
webmux kill-server
webmux rename -t NAME NEW
webmux has -t NAME
```

```console
$ webmux new -s work
work  →  http://localhost:7900

$ webmux new -s scrape -u https://example.com
scrape  →  http://localhost:7901

$ webmux ls
work    7900  3 tabs  shop.example.com/cart    ●
scrape  7901  1 tab   example.com

$ webmux attach -t work        # 用默认浏览器打开观看页面
$ webmux attach -t work -p     # 只打印 URL,不开浏览器(无 GUI 环境用)
http://localhost:7900?token=...

$ webmux attach -t work --read-only    # 只读 token,发给别人看
http://localhost:7900?token=<view-token>
```

- `-p PORT` 不给就自动从 7900 往上找空闲端口
- `-d` 建完不 attach(默认就是不 attach,`-d` 只是为了跟 tmux 的手感一致)
- **detach 不需要命令**——关掉网页就是 detach,容器照跑
- `has` 只返回退出码,给脚本用:`webmux has -t work || webmux new -s work`
- `kill-server` 干掉所有 webmux 会话,不碰其他容器

## 4. tab

```bash
webmux new-tab    -t NAME [-u URL] [-n]      # -n = 建完不切过去
webmux tabs       -t NAME [-F FORMAT]
webmux select-tab -t NAME:2
webmux kill-tab   -t NAME:2
webmux move-tab   -t NAME:2 --to 0
webmux goto       -t NAME URL
webmux back       -t NAME
webmux forward    -t NAME
webmux reload     -t NAME
```

```console
$ webmux tabs -t work
0: 购物车        shop.example.com/cart      ●
1: 订单确认      shop.example.com/order/91
2: 帮助中心      help.example.com

$ webmux tabs -t work -F '#{tab_id} #{tab_url}'
t_3 https://shop.example.com/cart
t_7 https://shop.example.com/order/91
t_9 https://help.example.com
```

`-F` 的占位符和 tmux 同款写法:
`#{tab_id}` `#{tab_index}` `#{tab_title}` `#{tab_url}` `#{tab_active}` `#{tab_loading}`
`#{session_name}` `#{session_port}` `#{tab_count}`

## 5. 操作

```bash
webmux click   -t NAME "登录"
webmux click   -t NAME --role button --name 登录
webmux type    -t NAME --label 手机号 13800000000
webmux key     -t NAME Enter
webmux scroll  -t NAME --dy 400
webmux wait    -t NAME --text "订单已提交" [--timeout 10]
webmux send    -t NAME '<json>'          # 原始动作数组,对应 tmux send-keys
```

```console
$ webmux click -t work "提交订单"
✓ click → button "提交订单"  412ms
  → /order/9182   出现『订单已提交』

$ webmux click -t work "提交"
✗ not_found: 找不到「提交」
  候选:  button "提交订单"
         button "提交并支付"
         link   "提交反馈"
```

**定位失败会列出候选**,和 API 的 `candidates` 是同一份东西([agent.md §2](agent.md))。

`send` 是逃生舱,直接发 [agent.md §3](agent.md#3-动作表) 的动作数组,
CLI 没覆盖到的动作都能用它:

```bash
webmux send -t work '[{"type":"select","label":"城市","value":"上海"},
                      {"type":"click","text":"搜索"}]'
```

`--note "..."` 在任何操作命令上都能加,写进操作日志(对应 API 的 `note`):

```bash
webmux click -t work "提交订单" --note "购物车已确认,现在下单"
```

## 6. 看

```bash
webmux capture  -t NAME [--text | --shot FILE | --elements]
webmux observe  -t NAME [--shot FILE] [--json]
webmux url      -t NAME
webmux status   -t NAME
webmux log      -t NAME [-n 50] [-f] [--failed]
webmux watch    -t NAME [--types 'tab.*']
webmux bundle   -t NAME -o out.zip
```

```console
$ webmux url -t work
https://shop.example.com/cart

$ webmux capture -t work --text | head -3      # 对应 tmux capture-pane -p
购物车
共 2 件商品

$ webmux observe -t work                        # agent 观测,人也能看
[12] button  "提交订单"
[13] textbox "优惠码" = ""
[14] link    "返回购物车"        (需下滑)

$ webmux log -t work -n 3
14:22:03  💭 购物车已确认,现在下单
          click "提交订单" → button "取消订单"
          → /cancel  出现『订单已取消』
14:22:06  👤 人点了 (612,340)
14:22:09  ✗ click "确认" not_found

$ webmux log -t work -f                         # 跟着滚,像 tail -f
$ webmux watch -t work --types 'tab.*'          # 事件流
```

`log -f` 和 `watch` 都是流式,`Ctrl-C` 退出。
`--json` 在所有读命令上可用,输出就是 API 的原始响应——**方便和 API 混着用**。

## 7. 没有 webmux server

tmux 有个 server 进程管所有 session。webmux **不需要**:

- 会话就是容器,`webmux ls` 直接 `docker ps --filter label=webmux.session`
- 元数据存在容器 label 上(`webmux.session=work`、`webmux.port=7900`)
- CLI 是个无状态的薄壳:会话级命令调 docker,其余命令调那个容器的 HTTP API

所以没有 `webmux start-server`,也不存在 server 挂了会话全丢的问题。
`docker ps` 看得到的就是全部真相。

## 8. 远端

```bash
webmux -H https://browser.internal:7900 tabs
export WEBMUX_HOST=https://browser.internal:7900
export WEBMUX_TOKEN=...
```

指定 `-H` 时**会话级命令不可用**(`new` / `ls` / `kill` 要 docker,远端没有),
其余命令照常。`-H` 和 `-t` 互斥。

## 9. 配置

`~/.webmux.conf`,tmux 的 `set -g` 写法:

```conf
set -g image        webmux/operator:1.0
set -g port-base    7900
set -g viewport     1280x800
set -g log-limit    500
set -g human-yield  3000
set -g attach-cmd   "firefox %u"      # %u = 观看 URL
```

命令行参数 > 环境变量 > 配置文件 > 内置默认。
配置项名字和容器的 `WEBMUX_*` 环境变量一一对应(`log-limit` ↔ `WEBMUX_LOG_LIMIT`)。

## 10. 退出码

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
| 7 | 容器出事了(`chrome_gone`) |

4/5/6 是**可重试**的,7 该告警——和 API 的错误二分一致([README §4](README.md#4-错误))。

## 11. CLI ↔ API 对照

CLI 不做任何 API 没有的事,每条命令就是一次调用:

| CLI | API |
| --- | --- |
| `new` | `docker run` |
| `ls` | `docker ps --filter label=webmux.session` |
| `attach` | `POST /api/live-token` → 打开观看页面 |
| `kill` | `docker rm -f` |
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
