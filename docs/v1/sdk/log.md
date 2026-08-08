# lib · 操作日志

导出成 [api/log.md](../api/log.md)。

**日志是整个 session 的,不分 tab**,所以挂在 `web` 上,不在 `Tab` 下:

```python
for e in web.log(limit=100, after=42, only="failed"):
    print(e.seq, e.at, e.user, e.note, e.action, e.hit, e.ok, e.after.changed)

web.log(user="claudecode")     # 只看某个署名干了什么
web.log(tab="t_7")             # 只看某个 tab
web.bundle("out.zip")          # 日志 + 截图 + 离线 HTML
```

**一定发请求**,它不在内存里。

## 1. 这是完整的操作路径

`e.user == "human"` 的条目是人在 VNC 里干的 —— 日志里既有你的代码干的,
也有人干的,是**一条完整的路径**,不是"只有 API 干过的事"。

```
14:22:03 💭 claudecode:购物车里已有一张票,现在去确认支付
         click "提交订单" → 命中 button "取消订单"    ← 一眼看出认错了元素
         → /cancel  出现『订单已取消』
14:22:06 👤 human:点了 (612,340)
```

## 2. `note` 是这套东西的核心

webmuxd **不产生思考**,但它提供一个**思考与后果对齐的存放位置**。

`tab.act(..., note="...")` 把这一步的想法挂上去,下面紧跟着就是它实际命中了什么、
页面变成了什么样。回看时一眼能看出是判断错了还是页面变了。

不传也能用,只是少了最有用的一列。

## 3. 条目字段

```python
e.seq  e.at  e.tab
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

## 4. 会被截断

环形保留 `WEBMUXD_LOG_LIMIT` 条(默认 500),老的连截图一起删 ——
就是 tmux 的 `history-limit`。要长期留就自己定时拉,或者 `web.bundle()` 打包。

## 5. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `web.log(limit=, after=, only=, user=, tab=)` | `GET /api/log?...` |
| `web.bundle(path)` | `GET /api/log/bundle` |
| 实时跟着滚 | `WS /api/events` 的 `log.appended`,见 [events.md](events.md) |
