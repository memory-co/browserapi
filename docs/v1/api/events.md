# 事件流

```
WS /api/events?after=118&types=tab.*,action.*
```

一条 WS 推全部事件。tab 条的实时刷新、动作直播、日志滚动,都从这里来。

`tab.*` 这几个是**怎么被采集到的**,见 [works/06](../works/06-tab-sync.md)。

## 1. 事件不是日志

两者长得像 —— 共用 `seq`、字段也重叠 —— 但**用途相反**:

| | 事件流 `WS /api/events` | 操作日志 [`GET /api/log`](log.md) |
| --- | --- | --- |
| 是什么 | **变化的通知**:刚刚怎么了 | **做过什么的账**:谁、干了、结果如何 |
| 存哪 | **内存**,最近 1000 条 | **磁盘**,一个 tab 一个 jsonl |
| 怎么拿 | 推 | 拉 |
| 会不会丢 | **会** —— 断线补不上就发 `gap`(§2) | 不会,只会从头被环形截断 |
| 覆盖什么 | 一切变化,包括没人"做"的 | 只有**动作**和 **tab 生老病死** |

**一次 `click` 的产出不对称:**

```
事件:action.started → page.navigated → tab.updated{title}
      → tab.updated{loading:false} → action.done → log.appended     6 条
日志:                                                                1 条
```

反过来,`tab.updated{loading:true}` 只有事件、没有日志 —— **没有人"做"它**,
它只是页面自己在加载。

**共用 `seq` 是刻意的**,不是巧合:拿一条日志的 `seq`,就能在事件流里找到它前后
发生了什么。两边对得齐。

> **别拿事件当账。** 它会丢、会被 1000 条挤掉、而且进程重启就没了。
> 要回看就读日志 —— 那才是落盘的那份。
> `log.appended` 是两者的接缝:它是"刚写了一条日志"这个**通知**。

## 2. 信封

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

## 3. 事件字典

### tab —— 画 tab 条用

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

### action —— 动作直播用

| type | 字段 | 什么时候 |
| --- | --- | --- |
| `action.started` | `seq`, `tab`, `action`, `target`, `note`, `user` | 动作开始派发 |
| `action.done` | `seq`, `ok`, `ms`, `hit`, `after`, `shot` | 动作完成(成功或失败) |
| `log.appended` | `entry` | 日志新增一条(等价于 `action.done` 落库后) |

`action.started` 里带 `note` 和 `user`,所以直播面板能在动作发生**之前**就显示
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

## 4. 客户端该怎么写

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
