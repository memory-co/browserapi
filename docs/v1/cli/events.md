# CLI · 事件流

对应 [api/events.md](../api/events.md)。两条流式命令,`Ctrl-C` 退出。

```bash
webmuxd log   -t NAME -f                         # 平时你要的是这个
webmuxd watch -t NAME [--types 'tab.*'] [--json]  # 排查同步问题时才用
```

**两个不是一个东西。** `log -f` 跟的是**账**(谁做了什么);`watch` 吐的是
**同步机制的原始流**,里面大量是"标题变了""loading 变了"这类没人"做"的变化。

要看它干了什么就用 `log -f`;怀疑外面那条 tab 条没跟上、或者在写自己的 UI,才用 `watch`。

## 1. `watch` —— 全部事件

```console
$ webmuxd watch -t work --types 'tab.*'
14:22:01  tab.created    t_7  help.example.com        (link_target_blank)
14:22:01  tab.activated  t_7  ← t_3
14:22:03  tab.updated    t_7  title="帮助中心" loading=false
14:22:09  tab.closed     t_7  → active t_3
```

`--types` 就是 API 的 `?types=`,支持 `*` 前缀过滤,逗号分隔多个。
`--json` 每行一个原始事件信封,给 `jq` 用:

```bash
webmuxd watch -t work --json | jq -r 'select(.type=="action.done") | .ms'
```

## 2. `log -f` —— 只跟操作日志

```console
$ webmuxd log -t work -f
14:22:03  💭 购物车已确认,现在下单
          click "提交订单" → button "取消订单"
          → /cancel  出现『订单已取消』
14:22:06  👤 人点了 (612,340)
```

像 `tail -f`。实现上它订阅的是 `action.started` / `action.done` / `log.appended`,
不是轮询 `GET /api/log`。

`action.started` 里带 `note`,所以 `💭` 那一行在动作**发生之前**就打出来了 ——
你能看见它打算干什么,然后才看见结果。

## 3. 断线和丢事件

CLI 自动带 `?after=<最后一条 seq>` 重连(服务端保留最近 1000 条)。
丢了就丢了,**不假装没丢**:

```console
⚠ gap 118→204:漏了 86 条,已重新拉全量
```

收到 `gap` 或 `chrome.restarted` 时,CLI 重新 `GET /api/tabs` + `GET /api/status`
再继续跟——和 [api/events.md §5](../api/events.md#5-客户端该怎么写) 说的一样。
`--json` 模式下 `gap` 事件**照样吐给你**,该重拉全量的是你的下游脚本。

## 4. ↔ API 对照

| CLI | API |
| --- | --- |
| `watch` | `WS /api/events` |
| `watch --types 'tab.*'` | `WS /api/events?types=tab.*` |
| 重连 | `WS /api/events?after=<seq>` |
| `log -f` | `WS /api/events?types=action.*,log.*` |

server 级的事件流(`session.created` / `session.died` 等,
[api/server.md §4](../api/server.md#4-事件))CLI 里没有对应命令 ——
要监这个就 `webmuxd -H ... --json` 之外自己连 WS,或走
[sdk/events.md](../sdk/events.md) 的 `Server().watch()`。
