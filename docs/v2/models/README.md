# models · DTO

**一句话**:四个大类 —— **session · tab · page · frame** ——
每一类在**每一条传输介质**上各长什么样。

落地在 [`webmuxd/models.py`](../../../webmuxd/models.py) 和
[`webmuxjs/client/src/protocol/messages.ts`](../../../webmuxjs/client/src/protocol/messages.ts)。

## 1. 它们的关系

```
  ~/.webmuxd.json ── HostEnvs          机器的事实,不属于任何 session(§5)
         │
         ▼
  ┌──────────────────────────────────────────────────────┐
  │  一个 server —— 一个口                                │
  └──────────────────────────┬───────────────────────────┘
                             │  SessionRow[]
                             ▼
  ┌──────────────────────────────────────────────────────┐
  │  Session                                             │
  │   一个浏览器 + 一份画面 + 一条流水                     │
  └───┬──────────────────────────────────────────┬───────┘
      │                                          │
      │  Tab × N                                 │  Frame × 1
      ▼                                          ▼
  ┌───────────────────┐                 ┌────────────────────────┐
  │  Tab   TabInfo    │                 │  Frame                 │
  │  开、关、切、导航   │ ◄──── 跟着 ──── │  28 字节头 + 一整张图   │
  └────────┬──────────┘   前台那个       │  + 六条下行消息         │
           │                             └────────────────────────┘
           │  当前这一页(没有自己的 id)              ▲
           ▼                                        │ 输入反着走
  ┌───────────────────────────────────┐             │ 同一条通道
  │  Page                             │ ────────────┘
  │  Element / Snapshot / ActionResult│
  └───────────────────────────────────┘
```

三条关系值得单说:

- **`Frame` 挂在 Session 上,不挂在 Tab 上。** 一个 session 一份画面,
  所有观看者看同一个 tab([f §6](../works/f-tabs.md#6-一个-session-一份画面))。
  它**跟着**前台那个 tab 走,但它不属于任何一个 tab。
- **`Page` 没有自己的 id。** 它就是"某个 tab 现在这一页" ——
  换一页,那一页上所有 `@e1` 一律作废([page §5](page.md#5-不出门的三个))。
- **输入和画面走同一条通道,方向相反。** 所以它在
  [frame](frame.md) 那一篇里,尽管它作用在 page 上。

## 2. 五条传输介质

| | 是什么 | 谁写谁读 |
| --- | --- | --- |
| **HTTP** | `/s/{sid}/api/*` 和 `/api/sessions` | SDK / CLI / 别人的 UI ⇄ 服务端 |
| **事件流** | `WS /s/{sid}/api/events` | 服务端 → 订阅者,**单向** |
| **画面下行** | `WS /s/{sid}/channel/cdp` 上的 JSON | 服务端 → 观看页,**单向、有第二个实现** |
| **画面上行** | 同一条 WS,反方向 | 观看页 → 服务端。**白名单,九种** |
| **落盘** | `log.jsonl` · `~/.webmuxd.json` | 跨的是**时间** |

## 3. 哪一类走哪几条

| | HTTP | 事件流 | 画面下行 | 画面上行 | 落盘 |
| --- | --- | --- | --- | --- | --- |
| [session](session.md) | `SessionRow` · status | `human.active` `chrome.restarted` `log.appended` … | `Hello` | — | `LogEntry` |
| [tab](tab.md) | `TabInfo` | `tab.created/updated/activated/closed` | — | `tab` | — |
| [page](page.md) | `Snapshot` `Element` `Locator` `ActionResult` `Pending` `Download` | `action.started/done` `download.*` `auth.required` `permission.changed` | — | — | 进 `LogEntry.fields` |
| [frame](frame.md) | `ModeInfo`(`/api/view/mode`) | — | `Cast` `Meta` `QualityChanged` `ModeInfo` `ModeError` `CursorChanged` + **二进制帧** | `ack` `mouse` `wheel` `key` `text` `resize` `mode` `ping` | — |
| [hostenv](hostenv.md) | — | — | — | — | `HostEnvs` |

**同一个 DTO 在不同介质上形状可以不同** —— 这正是要逐条写下来的原因。
最典型的是 `ModeInfo`:走 HTTP 时没有 `type`(URL 已经说明它是什么),
走 WS 时必须有(那是条流)。

## 4. 三条规矩

1. **一个概念一处定义。** 同一个 tab 记录不许服务端一份、SDK 一份 ——
   要 JSON 的自己 `to_json()`。
2. **不出门的字段要写明为什么。** `target_id` 是 CDP 句柄、`touched_at` 是
   LRU 内部 —— 它们**不上线**,而"为什么不上线"必须在表里说得出来。
3. **`from_json` 缺失只允许出现在画面下行那一组。** 下行是单向的;
   **别处缺 `from_json` 就是 SDK 读不回来**。

> 每张表里"JSON"那一列是**跑出来的**,不是照源码抄的 ——
> 有几个 `to_json()` 是条件写键(`if v: out[k] = v`),照源码读会读错。

## 5. 不在这四类里的一样

[hostenv](hostenv.md) —— `~/.webmuxd.json`。它是**机器的事实**,
`webmuxd install` 探一遍写下来,比任何 session 都活得久。
它跨的是时间,所以它是唯一一份**带版本号**的。

## 6. 今天对不齐的地方

四处,全部验实,细节在各自那一篇:

| # | 哪儿 | 什么情况 |
| --- | --- | --- |
| ① | `Meta` | 服务端在发,观看页**没有 `case "meta"`**,`messages.ts` 里也没这个 interface([frame §4](frame.md#4-meta--服务端在发观看页不认)) |
| ② | `pong` | 反过来:TS 有 interface,Python 侧手写 dict,**没有 DTO** |
| ③ | `Hello.protocol` | 发了 `28`,**两边都没人读** |
| ④ | `Cast.dsf` | Python 会发,`messages.ts` 里没声明 |

外加两处**字段名和键名不一样**却没写在别处:
`ViewMode.headed → needs_headed`、`HostEnvs.browser → default_browser`。
