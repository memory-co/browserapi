# 事件流

```
WS /api/events?after=118&types=tab.*,action.*
```

**这是同步机制,不是产品面。** 它存在只为一件事:**让外面那条 tab 条不用轮询**
([works/04](../works/04-chrome-ui-externalization.md))。

## 1. 谁该读这一篇

| 你在做什么 | 要不要碰事件流 |
| --- | --- |
| 用 TypeScript / Go 自己画一条 tab 条和地址栏 | **要**,这是唯一的实时来源 |
| 用 Python lib 写脚本或 agent | **不要** —— lib 已经替你订好了,`web.tabs` / `tab.url` 直接读内存 |
| 让模型驱动浏览器 | **不要** —— 模型的输入是 `observe()` 和日志,它不订阅任何东西 |
| 回看刚才发生了什么 | **不要** —— 那是[日志](log.md) |

**事件流没有一条是给模型看的。** 「它现在打算点什么」这种实时面板是给**人**看的,
而那个人看的就是查看页面 —— 也就是上面第一行。

## 2. 它和日志不是一回事,也不是一个层级

| | 事件流 | [操作日志](log.md) |
| --- | --- | --- |
| 是什么 | **同步机制**:让 UI 跟上变化 | **账**:谁做了什么、结果如何 |
| 谁读 | 画 UI 的 | **所有人** —— 人回看、模型看历史、出事了查 |
| 存哪 | 内存,最近 1000 条,重启就没 | 磁盘,一个 tab 一个 jsonl |
| 会不会丢 | **会**,丢了发 `gap` | 不会 |
| 覆盖什么 | 一切变化,包括没人"做"的 | 只有动作和 tab 生老病死 |

**一次 `click` 的产出不对称**,这最能说明两者不是一回事:

```
事件:action.started → page.navigated → tab.updated{title}
      → tab.updated{loading:false} → action.done → log.appended     6 条
日志:                                                                1 条
```

反过来,`tab.updated{loading:true}` 只有事件没有日志 —— **没有人"做"它**,
是页面自己在加载。事件记**变化**,日志记**有人做了一件事**。

**共用 `seq` 是刻意的**:拿一条日志的 `seq` 就能在事件流里找到它前后发生了什么。
`log.appended` 是接缝 —— 它是"刚写了一条日志"这个**通知**,让查看页面右边那块面板
能实时滚,仅此而已。

> **别拿事件当账。** 它会丢、会被 1000 条挤掉、进程重启就没。要回看只能读[日志](log.md)。

## 3. 信封

每个事件都长这样:

```jsonc
{ "seq": 119,                          // 单调递增,全局唯一
  "at": "2026-08-08T14:22:03.412Z",
  "type": "tab.updated",
  /* ...各类型自己的字段 */ }
```

- **断线重连**带 `?after=<最后收到的 seq>` 续传,服务端保留最近 **1000** 条
- 超出保留范围时先推一条 `{"type":"gap","from":...,"to":...}`,
  **收到 `gap` 就该重新拉一次全量**(`GET /api/tabs`、`GET /api/status`),不要假装没丢
- `?types=` 按前缀过滤,支持 `*`
- 服务端每 15 秒发一个 WS ping
- **大字段不内联**:截图只给 URL,不塞 base64,否则事件流会被撑爆

## 4. 事件字典

### tab —— 画 tab 条用(**怎么采集到的**见 [works/06](../works/06-tab-sync.md))

| type | 字段 | 什么时候 |
| --- | --- | --- |
| `tab.created` | `tab`, `reason` | 新 tab 出现。`reason` 见 [tabs.md §4](tabs.md#4-事件) |
| `tab.updated` | `id`, `changed` | URL/标题/loading/前进后退可用性变了。**只发变化的字段** |
| `tab.activated` | `id`, `previous` | 切了 tab(不管是 API 切的还是人切的) |
| `tab.closed` | `id`, `active` | tab 关了,`active` 是关完之后哪个是当前 |

### viewport —— 重新裁 iframe 用

| type | 字段 | 什么时候 |
| --- | --- | --- |
| `viewport.changed` | `crop_top`, `screen` | 视频全屏(归 0)、开书签栏(变大)、改分辨率 |

收到就按新的 `crop_top` 调整外面那层 `overflow:hidden` 壳,见
[works/04 §2](../works/04-chrome-ui-externalization.md)。

### action —— 让查看页面的日志面板实时滚

| type | 字段 | 什么时候 |
| --- | --- | --- |
| `action.started` | `seq`, `tab`, `action`, `target`, `note`, `user` | 动作开始派发 |
| `action.done` | `seq`, `ok`, `ms`, `hit`, `after`, `shot` | 动作完成(成功或失败) |
| `log.appended` | `entry` | 日志新增一条(等价于 `action.done` 落库后) |

`action.started` 里带 `note` 和 `user`,所以查看页面能在动作发生**之前**就显示
"**谁**现在打算做什么、为什么"。

### 页面

| type | 字段 | 什么时候 |
| --- | --- | --- |
| `page.navigated` | `tab`, `from`, `to`, `kind` | 导航完成 |
| `page.dialog` | `tab`, `kind`, `message` | `alert`/`confirm`/`prompt` 被拦下,等外面回应 |
| `page.crashed` | `tab` | 渲染进程崩了 |
| `download.started` | `name`, `bytes_total` | |
| `download.done` | `name`, `url` | 用 `GET /api/download/{name}` 取 |

### 人

| type | 字段 | 什么时候 |
| --- | --- | --- |
| `human.active` | `at`, `kind` | 人在 VNC 里点了/敲了。触发 `busy_human` 让路窗口 |
| `human.idle` | — | 让路窗口结束,API 恢复可用 |

人的操作**同样会产生 `log.appended`**(`user: "human"`),所以操作日志是完整的路径,
不是只有 API 干过的事。

### 容器

| type | 字段 | 什么时候 |
| --- | --- | --- |
| `chrome.restarted` | `restarts` | Chrome 崩了被自动拉起。**tab 全丢了,该重新拉全量** |
| `status.changed` | `busy` | 忙/闲翻转 |
| `gap` | `from`, `to` | 事件有丢失,见 §1 |

## 5. 客户端该怎么写

```python
for e in events():
    if e.type == "gap" or e.type == "chrome.restarted":
        ui.reload_all(get_tabs(), get_status())     # 重新拉全量
    elif e.type.startswith("tab."):
        ui.apply_tab_event(e)                      # 局部更新,别整条替换(会闪)
    elif e.type == "viewport.changed":
        ui.set_crop(e.crop_top)
    elif e.type == "action.started":
        ui.log_pending(e.note, e.action)
    elif e.type == "action.done":
        ui.log_result(e.seq, e.ok, e.after)
```

三条要点:

1. **`gap` 和 `chrome.restarted` 必须重新拉全量。** 增量更新在这两种情况下一定会错。
2. **`tab.updated` 做字段级合并**,整条替换会让 tab 条闪烁、丢掉滚动位置。
3. **不要靠事件维护唯一真相。** 事件是为了不用轮询,不是为了替代 `GET`。
   任何时候拿不准,重新 `GET /api/tabs` 就对了。
