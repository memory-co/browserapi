# CLI · tab

对应 [api/tabs.md](../api/tabs.md)。tmux 的 window 就是这里的 tab。

## 1. 命令

```bash
webmuxd new-tab    -t NAME [-u URL] [-n]      # -n = 建完不切过去
webmuxd tabs       -t NAME [-F FORMAT]
webmuxd select-tab -t NAME:2
webmuxd kill-tab   -t NAME:2
webmuxd move-tab   -t NAME:2 --to 0
webmuxd goto       -t NAME URL
webmuxd back       -t NAME
webmuxd forward    -t NAME
webmuxd reload     -t NAME [--ignore-cache]
```

`-t` 的 `session:tab` 写法见 [README §2](README.md#2-目标语法--t)。
`select-tab -t work:购物车` 这种按标题匹配是**客户端**干的:
先 `GET /api/tabs`,匹配唯一才发 `activate`,不唯一就退出码 2 并列候选。

## 2. 列出

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

`-F` 的占位符和 tmux 同款写法,每一个都直接取自 Tab 对象
([api/tabs.md §1](../api/tabs.md#1-tab-对象)):

| 占位符 | 来自 |
| --- | --- |
| `#{tab_id}` `#{tab_index}` `#{tab_title}` `#{tab_url}` | Tab 的同名字段 |
| `#{tab_active}` `#{tab_loading}` | 同上,输出 `1`/空 |
| `#{tab_security}` `#{tab_crashed}` | 同上 |
| `#{session_name}` `#{session_port}` `#{tab_count}` | 来自 `GET /api/sessions` |

`--json` 直接吐 `GET /api/tabs` 的原始响应,`favicon` 字段是 URL 不是字节。

## 3. 关最后一个 tab

和 API 一样,**永远至少留一个 tab**:关掉最后一个时会自动开一个 `about:blank`。

```console
$ webmuxd kill-tab -t work:0
✓ 关掉 t_3;只剩它了,已新建 about:blank (t_11)
```

这不是 CLI 的贴心,是 [api/tabs.md §3](../api/tabs.md#3-写) 的行为——
Chrome 关掉最后一个 tab 会连窗口一起关。

## 4. 特权页面去不了

```console
$ webmuxd goto -t work chrome://settings
✗ blocked_url: chrome:// 这类页面被禁掉了
```

退出码 2。不是技术上做不到,是**不该做** —— `chrome://settings` 里的东西该用容器的
启动参数配,不该让人或 agent 跑去点它([api/tabs.md §3](../api/tabs.md#3-写))。

## 5. 后退不动就报错

```console
$ webmuxd back -t work
✗ bad_request: 没得后退了
```

退出码 2。**不静默无操作**——脚本里 `back` 成功和没得后退是两回事,
和你 UI 上按钮的禁用状态要对得上。

## 6. ↔ API 对照

| CLI | API |
| --- | --- |
| `tabs` | `GET /api/tabs` |
| `tabs -t NAME:2` | `GET /api/tabs/{id}`(id 先本地解析) |
| `new-tab -u URL [-n]` | `POST /api/tabs` `{url, active}`(`-n` → `active:false`) |
| `select-tab` | `POST /api/tabs/{id}/activate` |
| `kill-tab` | `DELETE /api/tabs/{id}` |
| `move-tab --to N` | `POST /api/tabs/reorder` `{order:[...]}`(客户端算出整个排列) |
| `goto URL` | `POST /api/tabs/{id}/goto` `{url}` |
| `back` `forward` `reload` | `POST /api/tabs/{id}/back` `/forward` `/reload` |
| `reload --ignore-cache` | `POST /api/tabs/{id}/reload` `{ignore_cache:true}` |

**CLI 没覆盖的**:`GET /api/tabs/{id}/history`、`GET /api/tabs/{id}/favicon`、
`goto {history_index}`、`POST /api/tabs/{id}/stop`。
这几个是给画 tab 条的 UI 用的(长按后退弹历史、显示图标),终端里用不上。
真要用就 `--json` 加 `curl`,或者走 [sdk/tab/README.md](../sdk/tab/README.md)。

实时刷新 tab 条不该轮询 `tabs`,该用 [events.md](events.md)。
