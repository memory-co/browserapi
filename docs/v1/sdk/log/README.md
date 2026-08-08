# lib · 日志

导出成 [api/log.md](../../api/log.md)。

**一个 session 一个 `log.jsonl`,一行一条。** 不分 tab、不分类型,全在里面 ——
要哪部分就筛哪部分,jsonl 本来就是给这么用的。

```python
web.log(limit=100)             # 全部
web.log(kind="tab")            # tab 的生老病死 → session.md
tab.log()                      # 这个 tab 的动作 → tab.md,= web.log(tab=tab.id)
web.bundle("out.zip")          # 日志 + 截图 + 离线 HTML
```

**一定发请求**,它不在内存里。

| 文件 | 讲什么 |
| --- | --- |
| README.md(本文) | 有哪些类型、存哪、怎么切、和事件流的区别 |
| [tab.md](tab.md) | `kind="action"` —— 谁在哪个 tab 上做了什么 |
| [session.md](session.md) | `kind="tab"` / `kind="session"` —— tab 生老病死、Chrome 重启 |

## 1. 三类日志

每条都有 `kind`,只有三种:

| `kind` | 记什么 | 一条长什么样 | 详见 |
| --- | --- | --- | --- |
| `action` | **有人做了一件事** —— 点击、输入、导航、观测 | `click "提交订单" → 命中 button "取消订单"` | [tab.md](tab.md) |
| `tab` | **tab 的生和死** —— 建了、关了、被挤掉了 | `t_7 opened (link_target_blank, human)` | [session.md](session.md) |
| `session` | **整个 session 的事** —— Chrome 崩了重拉、`reset` | `chrome_restarted (restarts: 1)` | [session.md](session.md) |

**没有第四类。** 页面自己的变化(标题变了、loading 变了)**不进日志** ——
没有人"做"它们。那些只是内部的同步通知,不是账
([works/06 §5](../../works/06-tab-sync.md#5-推给客户端))。

共同字段:

```python
e.seq   e.at   e.kind   e.user   e.tab      # e.tab 在 kind="session" 时为 None
```

`seq` 全局单调,和事件流共用一个计数器,所以两边对得齐。

## 2. 存哪、怎么切

```
/data/
├── log.jsonl        ← 当前这一刀
├── log.1.jsonl      ← 上一刀
└── shots/0042.webp  ← 按 seq 命名
```

**满 `WEBMUXD_LOG_LIMIT` 条(默认 5000)就切一刀**:当前文件改名 `log.1.jsonl`,
开一个新的。**只留上一刀** —— 再切时 `log.1.jsonl` 被盖掉,连同它那批 seq 的截图一起删。

所以在线记录**永远在 5000~10000 条之间**。按每条 ~100KB 截图算,磁盘约 1GB 封顶。

**这是 tmux 的 `history-limit`,不是归档系统。** 要长期留就自己定时拉,或者 `bundle()`。

> **代价说清楚**:滚掉的那批里如果有 tab 的生死记录,也一起没了。
> tab 上限是 10、一个 tab 两行,要靠生死记录填满一万行得开关五千次 ——
> 实际上动作记录先滚。真要长期留就自己拉。

## 3. 按 tab 读就是过滤

```python
tab.log()                      # lib 帮你带上 ?tab=
web.log(tab="t_7")             # 一样
```

```bash
grep '"tab":"t_7"' /data/log.jsonl        # 直接在容器里 grep 也行
grep '"kind":"tab"' /data/log.jsonl       # tab 的生老病死
grep '"ok":false' /data/log.jsonl         # 失败的
```

**一行一条 JSON,就是为了这个。** 不为按 tab 分文件 —— 一万行的量级,
筛一遍的成本可以忽略,而分文件要多一套目录生命周期。

## 4. 这是完整的操作路径

`e.user == "human"` 的条目是人在 VNC 里干的 —— 日志里既有你的代码干的,
也有人干的,是**一条完整的路径**,不是"只有 API 干过的事"。

```
14:22:03 💭 claudecode:购物车里已有一张票,现在去确认支付
         click "提交订单" → 命中 button "取消订单"    ← 一眼看出认错了元素
         → /cancel  出现『订单已取消』
14:22:06 👤 human:点了 (612,340)
```

## 5. `note` 是这套东西的核心

webmuxd **不产生思考**,但它提供一个**思考与后果对齐的存放位置**。

`tab.act(..., note="...")` 把这一步的想法挂上去,下面紧跟着就是它实际命中了什么、
页面变成了什么样。回看时一眼能看出是判断错了还是页面变了。不传也能用,只是少了最有用的一列。

## 6. 这是唯一能回看的地方

容器里还有一条 WS 在推变化通知,但那是上层 UI 和 lib 用的**同步机制**,
不是账:会丢、只留 1000 条、进程重启就没
([works/06 §5](../../works/06-tab-sync.md#5-推给客户端))。

**要回看只能读这儿。**

## 7. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `web.log(limit=, after=, only=, user=, tab=, kind=)` | `GET /api/log?...` |
| `tab.log()` | `GET /api/log?tab={id}` |
| `web.bundle(path)` / `tab.bundle(path)` | `GET /api/log/bundle[?tab=]` |
| `e.shot` | `GET /api/log/{seq}/shot` |
