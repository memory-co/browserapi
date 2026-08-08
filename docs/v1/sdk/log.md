# lib · 操作日志

导出成 [api/log.md](../api/log.md)。**单个 tab 的记录在 [tab/log.md](tab/log.md)**,
这儿讲的是跨 tab 的那部分。

**别和事件流搞混**:事件是内存里的变化通知(会丢),日志是磁盘上的账(不丢)。
共用 `seq` 所以能对齐,但要回看只能读这儿 ——
见 [api/events.md §1](../api/events.md#1-事件不是日志)。

```python
for e in web.log(limit=100, after=42, only="failed"):
    print(e.seq, e.at, e.user, e.note, e.action, e.hit, e.ok, e.after.changed)

web.log(user="claudecode")     # 只看某个署名干了什么
web.log(kind="tab")            # tab 的生老病死,见 §2
tab.log()                      # 这一个 tab 的,= web.log(tab=tab.id)

web.bundle("out.zip")          # 全部:日志 + 截图 + 离线 HTML
tab.bundle("t_7.zip")          # 就这一个 tab
```

**一定发请求**,它不在内存里。

磁盘上**一个 tab 一个文件**,所以 `tab.log()` 是读一个文件不是过滤
([works/03 §3.1](../works/03-view-and-log.md#31-一个-tab-一个文件))。
但 `web.log()` 按 `seq` 归并,**全序是完整的** —— 分文件是存储布局,不是把时间线切开。

## 2. tab 的生老病死

```python
for e in web.log(kind="tab"):
    print(e.tab, e.event, e.at, e.reason, e.user)
    # t_7 opened 14:22:01 link_target_blank human
    # t_7 closed 14:31:44 —        api
```

**这是持久的。** `web.watch("tab.*")` 给的是事件流,内存里最近 1000 条,重启就没了;
这一份落盘且不截断,所以**已经关掉的 tab 也查得到**。

`web.tabs` 只有活着的;要历史就查这儿。

## 3. 这是完整的操作路径

`e.user == "human"` 的条目是人在 VNC 里干的 —— 日志里既有你的代码干的,
也有人干的,是**一条完整的路径**,不是"只有 API 干过的事"。

```
14:22:03 💭 claudecode:购物车里已有一张票,现在去确认支付
         click "提交订单" → 命中 button "取消订单"    ← 一眼看出认错了元素
         → /cancel  出现『订单已取消』
14:22:06 👤 human:点了 (612,340)
```

## 4. `note` 是这套东西的核心

webmuxd **不产生思考**,但它提供一个**思考与后果对齐的存放位置**。

`tab.act(..., note="...")` 把这一步的想法挂上去,下面紧跟着就是它实际命中了什么、
页面变成了什么样。回看时一眼能看出是判断错了还是页面变了。

不传也能用,只是少了最有用的一列。

## 5. 条目字段

```python
e.seq  e.at  e.tab  e.kind        # action | tab | session
e.user            # 署名,见 ../README.md §4
e.note            # act() 传的
e.action          # click / type / goto ...
e.target          # 你给的定位
e.hit             # 实际命中的元素:role / name / bbox
e.ok  e.ms
e.after.url  e.after.changed     # 「出现『订单已取消』」
e.shot            # 截图 URL
e.background      # 对非激活 tab 操作的
e.opaque          # js / 坐标点击 = true,UI 标黄
```

字段就是 [api/log.md](../api/log.md) 的日志条目,原样映射成属性。

## 6. 会被截断

**每个 tab** 环形保留 `WEBMUXD_LOG_LIMIT` 条(默认 500),已关闭 tab 的目录留最近
`WEBMUXD_TAB_KEEP` 个 —— 就是 tmux 的 `history-limit`,和 tmux 一样**按 pane 算**。

`kind="tab"` 那份**不截断**:目录得比细节活得久,所以哪怕某个 tab 的逐步记录已经清了,
"它存在过、什么时候关的"还在。

要长期留就自己定时拉,或者 `bundle()` 打包。

## 7. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `web.log(limit=, after=, only=, user=, tab=, kind=)` | `GET /api/log?...` |
| `tab.log()` | `GET /api/log?tab={id}` |
| `web.bundle(path)` | `GET /api/log/bundle` |
| `tab.bundle(path)` | `GET /api/log/bundle?tab={id}` |
| 实时跟着滚 | `WS /api/events` 的 `log.appended`,见 [events.md](events.md) |
