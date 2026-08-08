# SDK · 事件流

对应 [api/events.md](../api/events.md)。

## 1. `b.watch()`

阻塞式生成器,`for` 起来就行:

```python
for e in b.watch():
    print(e.seq, e.type)

for e in b.watch("tab.*"):           # 前缀过滤,= ?types=
    ui.update(e)

for e in b.watch(after=118):         # 从某个 seq 之后续传
    ...
```

事件对象就是 [api/events.md §1](../api/events.md#1-信封) 的信封,
`e.seq` `e.at` `e.type` 加各类型自己的字段(`e.tab` `e.changed` `e.note` …),
访问不存在的字段返回 `None` 而不是抛 —— 事件字典只增不减,新字段不该让老代码崩。

`e.raw` 是原始 dict,有新字段 SDK 还没建模时从这里拿。

## 2. 断线自动续传,但 `gap` 不吞

SDK 断线后自动带 `?after=<最后一条 seq>` 重连(服务端保留最近 1000 条)。
超出保留范围时,**`gap` 事件照样吐给你**:

```python
for e in b.watch():
    if e.type in ("gap", "chrome.restarted"):
        ui.reload_all(b.tabs(), b.status())        # 重新拉全量
    elif e.type.startswith("tab."):
        ui.apply_tab_event(e)                      # 局部更新,别整条替换(会闪)
    elif e.type == "viewport.changed":
        ui.set_crop(e.crop_top)
    elif e.type == "action.started":
        ui.log_pending(e.note, e.action)
    elif e.type == "action.done":
        ui.log_result(e.seq, e.ok, e.after)
```

**重连 SDK 替你做,重新拉全量它不替你做。** 因为它不知道你缓存了什么 ——
自动重拉只会让你以为增量是可靠的。三条要点和 API 那边完全一样
([api/events.md §3](../api/events.md#3-客户端该怎么写)):

1. `gap` 和 `chrome.restarted` 必须重新拉全量
2. `tab.updated` 做字段级合并,整条替换会闪
3. 不要靠事件维护唯一真相 —— 拿不准就重新 `b.tabs()`

## 3. 退出

```python
w = b.watch("action.*")
for e in w:
    if e.type == "action.done" and e.seq >= target:
        break                 # 退出 for 即关闭 WS

with b.watch() as w:          # 也可以显式管理
    for e in w:
        ...
```

`b.watch()` 会阻塞当前线程。要一边监听一边操作,就另起一个线程 ——
但**别在两个线程里共用同一个 `Browser`**([README §4](README.md#4-并发)),
监听那个线程用自己的实例。

## 4. server 级事件

```python
for e in Server().watch():
    if e.type == "session.died":
        alert(e.name)
```

对应 [api/server.md §4](../api/server.md#4-事件),和 session 级的事件流是两条,
别指望在 `b.watch()` 里收到 `session.*`。

## 5. ↔ API 对照

| SDK | API |
| --- | --- |
| `b.watch()` | `WS /api/events` |
| `b.watch("tab.*")` | `WS /api/events?types=tab.*` |
| `b.watch(after=n)` | `WS /api/events?after=n` |
| 自动重连 | 断线后重发 `?after=<last seq>` |
| `Server().watch()` | server 的 `WS /api/events` |

事件类型不在 SDK 里另建一套枚举 —— **字符串就是 API 那个字符串**,
[api/events.md §2](../api/events.md#2-事件字典) 那张字典是唯一的一份。
