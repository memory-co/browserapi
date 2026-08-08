# lib · 事件流

导出成 [api/events.md](../api/events.md)。

**写脚本或 agent 的话,这一篇你不用看。** lib 已经替你订好了 ——
`web.tabs` / `tab.url` 读的就是它维护的那份内存
([README §3](README.md#3-tab-的状态在内存里)),你不需要自己处理事件。

`web.watch()` 是给**你要自己画 UI** 的时候用的:一块面板、一条自定义的 tab 条、
一个把动作推给别处的桥。除此之外都不需要。

**模型更不需要。** 它的输入是 `observe()` 和[日志](log/),它不订阅任何东西。

> 事件是内存里的**变化通知**(会丢、1000 条上限、重启就没),
> 日志是磁盘上的**账**(不丢)。共用 `seq` 所以对得齐,但**要回看只能读日志** ——
> 见 [api/events.md §2](../api/events.md#2-它和日志不是一回事也不是一个层级)。

## 1. `web.watch()`

阻塞式生成器,`for` 起来就行:

```python
for e in web.watch():
    print(e.seq, e.type)

for e in web.watch("tab.*"):         # 前缀过滤,= ?types=
    ui.update(e)

for e in web.watch(after=118):       # 从某个 seq 之后补,服务端保留最近 1000 条
    ...
```

事件对象就是 [api/events.md §3](../api/events.md#3-信封) 的信封,
`e.seq` `e.at` `e.type` 加各类型自己的字段(`e.tab` `e.changed` `e.note` `e.user` …),
访问不存在的字段返回 `None` 而不是抛 —— 事件字典只增不减,新字段不该让老代码崩。

`e.raw` 是原始 dict,有新字段 lib 还没建模时从这里拿。
`tab.*` 事件的 `e.tab` 已经是**句柄**,不是 id。

## 2. 大部分时候你不需要它

因为 tab 条那一层的状态**已经在内存里了**:

```python
# 不用这么写
for e in web.watch("tab.*"):
    my_tab_bar.apply(e)

# 直接读就行,值一直是新的
my_tab_bar.render(web.tabs, web.active)
```

`watch()` 真正有用的是**内存里没有的那些事件**:

| 你想要 | 事件 |
| --- | --- |
| 面板上显示「下一步打算干什么」 | `action.started`(带 `note` 和 `user`) |
| 动作结果、耗时、截图 | `action.done` |
| 日志滚动 | `log.appended` |
| 人上手了 | `human.active` / `human.idle` |
| 弹窗等着回应 | `page.dialog` |
| 下载好了 | `download.done` |
| 外面 iframe 该重新裁了 | `viewport.changed` |

```python
for e in web.watch("action.*"):
    if e.type == "action.started":
        print(f"{e.user} 打算:{e.note}")
    else:
        print(f"  → {'✓' if e.ok else '✗'} {e.ms}ms")
```

## 3. 断线:重连 lib 做,重拉全量它替你做

这一条和上一版不一样,因为**现在内存归 lib 管**:

- WS 断了 → `web.stale = True`,后台一直重连,属性读退化成直接 GET
- 重连时带 `?after=<最后一条 seq>` 续传
- 收到 `gap` 或 `chrome.restarted` → **lib 自动重新拉全量**(`GET /api/tabs` + `/api/status`),
  因为那份表是它的责任

但 `gap` 事件**照样吐给你**,不吞:

```python
for e in web.watch():
    if e.type in ("gap", "chrome.restarted"):
        my_own_cache.reload()      # lib 的表它自己修好了,你的缓存你自己修
```

`chrome.restarted` 意味着 tab 全丢了,内存里那份表会整个换掉 —— 你手上的旧句柄
之后任何动作抛 `TabGone`。

## 4. 退出

```python
w = web.watch("action.*")
for e in w:
    if e.type == "action.done" and e.seq >= target:
        break                 # 退出 for 即取消订阅,底层 WS 照常留着

with web.watch() as w:        # 也可以显式管理
    for e in w:
        ...
```

`watch()` 阻塞当前线程。要一边监听一边操作,另起一个线程 ——
但**别在两个线程里共用同一个 `Webmuxd`**([README §6](README.md#6-并发)),
监听那个线程用自己的实例。

## 5. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| 内存里那份 tab 表 | 由 `WS /api/events` 的 `tab.*` 维护,不是端点 |
| `web.watch()` | `WS /api/events`(与内存共用同一条连接) |
| `web.watch("tab.*")` | `?types=tab.*` |
| `web.watch(after=n)` | `?after=n` |
| 自动重连 + 自动重拉全量 | 断线后 `?after=<last seq>`;收 `gap` 后 `GET /api/tabs` |
| `web.stale` `web.sync()` | 纯客户端状态 / `GET /api/tabs` + `/api/status` |
| — | server 级 `WS /api/events`(`session.*`)在 lib 里**没有对应** |

事件类型不在 lib 里另建一套枚举 —— **字符串就是 API 那个字符串**,
[api/events.md §4](../api/events.md#4-事件字典) 那张字典是唯一的一份。

`web.watch()` 只给你**这一个 session** 的事件。server 级的那条流
(`session.created` / `session.died`,[api/server.md §4](../api/server.md#4-事件))
lib 不给方法 —— 理由和没有 `Server` 类一样,见
[server.md §5](session.md#5-lib-不管有哪些-session)。
