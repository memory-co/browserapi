# 操作日志接口

`GET /api/log` —— 回看**这个 session 里发生过什么**,不分 tab。

人在 VNC 里的操作也在里面,所以这是一条完整的路径,不是"只有 API 干过的事"。

**这不是事件流。** 日志是**落盘的账**,事件是**内存里的通知** ——
两者共用 `seq`、字段也重叠,但会不会丢、能不能回看都不一样,
对照表在 [events.md §2](events.md#2-它和日志不是一回事也不是一个层级)。**要回看就读这儿。**

Python 侧见 [sdk/log/](../sdk/log/),命令行见 [cli/log.md](../cli/log.md)。

## 1. 拉

```
GET /api/log?limit=100&after=42&only=failed&user=claudecode&tab=t_3&kind=action
```

| 参数 | 说明 |
| --- | --- |
| `limit` `after` | 分页,`after` 是 `seq` |
| `tab` | 只要这个 tab 的 |
| `kind` | `action`(默认全给) / `tab`(生老病死) / `session`(chrome 重启、reset) |
| `user` | 只看某个署名 |
| `only` | `failed` 只看失败的 |

磁盘上就是**一个 `log.jsonl`**,一行一条,不分 tab 也不分类型
([works/03 §3.1](../works/03-view-and-log.md#31-一个文件))。
所有筛选都是过滤,`seq` 全局单调。

```jsonc
{ "entries": [
  { "seq": 42, "at": "14:22:03", "tab": "t_3",
    "note": "购物车里已有一张票,现在去确认支付",     // ← POST /api/act 的 note
    "action": "click", "target": { "text": "提交订单" },
    "hit": { "role":"button", "name":"取消订单", "bbox":[820,612,140,40] },
    "ok": true, "ms": 412,
    "after": { "url": "/cancel", "changed": "出现『订单已取消』" },
    "shot": "/api/log/42/shot",
    "user": "claudecode",        // 署名,见 §6.1。人在 VNC 里操作记 "human"
    "background": false,
    "opaque": false }            // js / 坐标点击 = true,UI 标黄
] }
```

**`note` 那一行是这套东西的核心。** webmuxd 不产生思考,但它提供一个
思考与后果对齐的存放位置。日志里长这样:

```
14:22:06 💭 claudecode:购物车里已有一张票,现在去确认支付
         click "提交订单" → 命中 button "取消订单"    ← 一眼看出认错了元素
         → /cancel  出现『订单已取消』
```

不传 `note` 也能用,只是回看时少了最有用的一列。

## 3. tab 的生老病死

```
GET /api/log?kind=tab
```

```jsonc
{ "seq": 118, "kind": "tab", "event": "opened",  "tab": "t_7",
  "url": "...", "title": "帮助中心", "reason": "link_target_blank",
  "opener": "t_3", "user": "human" }
{ "seq": 402, "kind": "tab", "event": "closed",  "tab": "t_7",
  "final_url": "...", "user": "api" }
```

**这是持久的,不是事件流。** `tab.created` / `tab.closed` 事件是内存里最近 1000 条
([events.md §3](events.md#3-信封)),重启就没了;这份落盘,
所以"那个已经关掉的 tab 什么时候建的、谁建的、关的时候停在哪"查得到 ——
直到被切走那一刀带走(§4)。

`GET /api/tabs` 只给**活着的** tab;要历史就查这里。

## 4. 保留

满 `WEBMUXD_LOG_LIMIT` 条(默认 5000)**切一刀**:当前文件改名 `log.1.jsonl`,开新的,
**只留上一刀**,再切时连同那批截图一起删。所以在线记录永远在 5000~10000 条之间。

**`kind=tab` 没有额外保护**,一起滚。真要长期留一份 tab 的生死账就自己定时拉。

```
GET /api/log/bundle              # 全部
GET /api/log/bundle?tab=t_7      # 只打包这个 tab 的条目和截图
```

zip 解开双击就能离线看。

## 2. `user` —— 署名,不是身份

`POST /api/act` 的 `user` 字段落进日志的 `user` 列,并出现在 `action.started` /
`action.done` 事件里。它解决的是**多个 agent 和人共用一个浏览器时,回看分不清谁干的**。

**服务端不校验它。** 拿着同一个 token 就能自称任意 `user` ——
安全边界是 token,不是这个字段。三条必须清楚:

| | |
| --- | --- |
| 它**不是**鉴权 | 想隔离就发不同的 token |
| 它**不是**锁 | 两个 `user` 同时发动作,照样一个拿到 `409 busy`([README §1](README.md#1-约定)) |
| 它**不影响**让路 | `busy_human` 看的是 VNC 上有没有真人在动,不是这个字段([README §5](README.md#5-人在操作时的让路)) |

不传时记 `"api"`。人在 VNC 里手动操作,服务端自己记 `"human"` ——
**所以日志是完整的操作路径**,不是"只有 API 干过的事"。

`GET /api/log?user=claudecode` 只看某一个署名做过什么。

