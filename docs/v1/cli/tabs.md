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
webmuxd stop       -t NAME                    # 停止加载
webmuxd dialog     -t NAME --accept [--text T] | --dismiss
```

**同时最多 `tab-max` 个(默认 10)**,`new-tab` 超了会挤掉最不活跃的那个,
并在输出里说是哪个([api/tabs.md §3](../api/tabs.md#3-写))。

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
$ webmuxd new-tab -t work -u https://example.com
✓ t_12  (已达上限 10,挤掉最不活跃的 t_4 — help.example.com)

$ webmuxd kill-tab -t work:0
✓ 关掉 t_3;只剩它了,已新建 about:blank (t_11)
```

这不是 CLI 的贴心,是 [api/tabs.md §3](../api/tabs.md#3-写) 的行为——
Chromium 关掉最后一个 tab 会连窗口一起关。

## 4. 弹窗挡住了

页面弹 `alert` / `confirm` / `prompt` 时**会挡住这个 tab**,`tabs` 里那一行会标出来:

```console
$ webmuxd tabs -t work
0: 结算    shop.example.com/checkout   ●  ⚠ confirm:确定要删除吗?

$ webmuxd dialog -t work --accept
✓ 已确定

$ webmuxd dialog -t work --accept --text 13800000000    # prompt
$ webmuxd dialog -t work --dismiss                      # 取消
```

**不自动回应** —— 该点确定还是取消是你的判断。挂着期间对这个 tab 的操作退出码 6(忙)。
(lib 那边这个方法叫 `tab.answer()`,[sdk/tab/navigate.md §5](../sdk/tab/navigate.md#5-弹窗挡住了)。)

## 5. 特权页面去不了

```console
$ webmuxd goto -t work chrome://settings
✗ blocked_url: chrome:// 这类页面被禁掉了
```

退出码 2。不是技术上做不到,是**不该做** —— `chrome://settings` 里的东西该用容器的
启动参数配,不该让人或 agent 跑去点它([api/tabs.md §3](../api/tabs.md#3-写))。

## 6. 后退不动就报错

```console
$ webmuxd back -t work
✗ bad_request: 没得后退了
```

退出码 2。**不静默无操作**——脚本里 `back` 成功和没得后退是两回事,
和你 UI 上按钮的禁用状态要对得上。

## 7. ↔ API 对照

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
| `stop` | `POST /api/tabs/{id}/stop` |
| `dialog --accept/--dismiss [--text]` | `POST /api/tabs/{id}/dialog` `{accept, text}` |

**CLI 没覆盖的**:`GET /api/tabs/{id}/history`、`GET /api/tabs/{id}/favicon`、
`goto {history_index}`。
这几个是给画 tab 条的 UI 用的(长按后退弹历史、显示图标),终端里用不上。
真要用就 `--json` 加 `curl`,或者走 [sdk/tab/README.md](../sdk/tab/README.md)。

要在别处实时刷一条 tab 条,轮询 `tabs` 就够用;想要实时的内部机制见
[works/06 §5](../works/06-tab-sync.md#5-推给客户端)。
