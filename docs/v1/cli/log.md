# CLI · 日志

对应 [api/log.md](../api/log.md)。tmux 的 scrollback。

```bash
webmuxd log    -t NAME [-n 50] [-f] [--failed] [--user NAME]
webmuxd bundle -t NAME -o out.zip
```

```console
$ webmuxd log -t work -n 3
14:22:03  💭 claudecode:购物车已确认,现在下单
          click "提交订单" → button "取消订单"
          → /cancel  出现『订单已取消』
14:22:06  👤 human:点了 (612,340)
14:22:09  ✗ click "确认" not_found
```

`💭` 是 `note`,`👤` 是 `user: "human"` —— **人在 VNC 里的操作同样进日志**,
所以这是完整的操作路径,不是只有 CLI 干过的事。

```bash
webmuxd log -t work --user claudecode    # 只看某个署名
webmuxd log -t work --failed             # 只看失败的
webmuxd log -t work -f                   # 跟着滚,像 tail -f
webmuxd bundle -t work -o out.zip        # 日志 + 截图 + 离线 HTML
```

`log -f` 是流式的,`Ctrl-C` 退出;它订的是事件流不是轮询,见 [events.md](events.md)。

## 三类日志

`log` 默认给你全部三类,按 `kind` 筛:

```bash
webmuxd log -t work --kind action     # 谁做了什么(默认占绝大多数)
webmuxd log -t work --kind tab        # tab 的生老病死
webmuxd log -t work --kind session    # Chrome 重启、reset
```

容器里也可以直接 grep,一行一条 JSON:

```bash
grep '"kind":"tab"' /data/log.jsonl
```

类型的完整说明见 [api/log.md](../api/log.md) 和 [sdk/log/](../sdk/log/)。

## ↔ API 对照

| CLI | API |
| --- | --- |
| `log -n N` | `GET /api/log?limit=N` |
| `log --failed` | `GET /api/log?only=failed` |
| `log --user X` | `GET /api/log?user=X` |
| `log --kind tab` | `GET /api/log?kind=tab` |
| `log -f` | `WS /api/events`,`action.*` + `log.appended` |
| `bundle -o F` | `GET /api/log/bundle` |
