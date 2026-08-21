# CLI · 动作与观测

对应 [api/act.md](../api/act.md)。**做**(`POST /api/act`)和**读**(`/api/screenshot`、`/api/text`)的命令行版。

tmux 的 `send-keys` ↔ `click`/`type`/`key`/`send`,`capture-pane` ↔ `capture`。
日志(scrollback)在 [log.md](log.md)。

## 1. 做

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

**定位失败会列出候选**(退出码 4),和 API 的 `candidates` 是同一份东西
([api/act.md §2](../api/act.md#2-post-apiact--做))。

定位写法五种,和 API 一一对应([api/act.md §4](../api/act.md#4-定位)):

| CLI | API 定位 |
| --- | --- |
| `webmuxd click -t w "提交订单"` | `{"text": "提交订单"}` |
| `--role button --name 登录` | `{"role":"button","name":"登录"}` |
| `--label 手机号` | `{"label":"手机号"}` |
| `--css '#pay'` | `{"css":"#pay"}` |
| `--at 890,632` | `{"point":[890,632]}` |
| `--nth 1` | `{"nth":1}` |

`--css` 和 `--at` 是逃生舱,日志里会标黄。

### `send` —— 逃生舱

直接发 [api/act.md §3](../api/act.md#3-动作表) 的动作数组,
CLI 没做成子命令的动作(`select` `check` `clear` `hover` `upload` `drag` `extract` `js` `tab_*`)
都能用它:

```bash
webmuxd send -t work '[{"type":"select","label":"城市","value":"上海"},
                      {"type":"click","text":"搜索"}]'
```

**一串动作一次往返,串行执行、遇错即停**——和 API 的语义完全一样。
`click`/`type`/`key` 这些子命令只是「只有一个动作的 `send`」。

## 2. 读

**`capture` 对应 tmux 的 `capture-pane`** —— 把里面的东西抓出来,
不给就是正文,给 `--shot` 就是一张图。

```bash
webmuxd capture  -t NAME [--shot FILE]
webmuxd url      -t NAME
webmuxd status   -t NAME
```

```console
$ webmuxd url -t work
https://shop.example.com/cart

$ webmuxd capture -t work | head -3       # 正文,对应 capture-pane -p
购物车
共 2 件商品

$ webmuxd capture -t work --shot p.webp   # 那一刻的页面
✓ 存到 p.webp
```

**`capture --shot` 指向非激活 tab 时会先把它切到前台**(画面会跳)——
Chromium 不渲染后台 tab。纯输入的 `click` / `type` 不用切。

> **没有"列元素"这个命令。** 元素表只服务定位(`click "提交订单"`),
> 不单独开口子 —— 理由见 [api/act.md §1](../api/act.md#1-读--一张图和正文)。

日志在 [log.md](log.md)。

## 3. note 参数

任何操作命令上都能加,写进操作日志(对应 API 的 `note`):

```bash
webmuxd click -t work "提交订单" --note "购物车已确认,现在下单"
```

webmuxd 不产生思考,但它提供一个思考与后果对齐的存放位置
([api/act.md §6](../api/log.md))。
不传也能用,只是回看时少了最有用的一列。

## 4. ↔ API 对照

| CLI | API |
| --- | --- |
| `click` `type` `key` `scroll` `wait` | `POST /api/act`,一个动作 |
| `send '<json>'` | `POST /api/act`,原样透传 `actions` |
| `--note` | `POST /api/act` 的 `note` |
| `--user` | `POST /api/act` 的 `user`(署名,不是鉴权) |
| `log --user X` | `GET /api/log?user=X` |
| `--timeout N` | `settle.timeout_ms` / `wait_for` 的超时 |
| `capture --text` | `GET /api/text` |
| `capture --shot` | `GET /api/screenshot` |
| `url` `status` | `GET /api/status` |

**CLI 没覆盖的**:`POST /api/upload`、`GET /api/download/{name}`、`POST /api/reset`、
`GET /api/viewport`、`GET /api/log/{seq}/shot`、
`POST /api/live-token`(用 [server.md](server.md) 的 `share`)。

`capture --shot` 拿的是**现拍的一张**;要日志里某一步或某次观测的那张,
用 `--json` 取到 URL 再 `curl`,或走 [sdk/tab/read.md §2](../sdk/tab/read.md#1-截图)。

跑循环让模型自己点,别在 shell 里拼 —— 那是 [sdk/tab/read.md](../sdk/tab/read.md) 的事。
CLI 适合的是手动探路、写死的脚本、和出事之后翻 [`log`](log.md)。
