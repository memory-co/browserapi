# lib · Tab · 记录

**这个 tab 干过什么。** 磁盘上它就是一个文件(`/data/tabs/<id>/log.jsonl`),
所以 `tab.log()` 是**读一个文件**,不是从大表里筛
([works/03 §3.1](../../works/03-view-and-log.md#31-一个-tab-一个文件))。

```python
for e in tab.log(limit=50, only="failed"):
    print(e.seq, e.at, e.user, e.note, e.action, e.hit, e.ok, e.after.changed)

tab.bundle("t_7.zip")     # 打包这个 tab 的目录:日志 + 截图 + 离线 HTML
```

整个 session 的(跨 tab 归并、tab 的生老病死)在 [../log.md](../log.md)。

## 1. 一条长什么样

```python
e.seq             # 全局单调,和事件流是同一个计数器 —— 见 ../events.md §1
e.at
e.kind            # 这里恒为 "action"
e.user            # 署名
e.note            # act() 传的那句思考
e.action          # click / type / goto ...
e.target          # 你给的定位:{"text": "登录"}
e.hit             # 实际命中的:role / name / bbox
e.ok  e.ms
e.after.url  e.after.changed     # 「出现『订单已取消』」
e.shot            # 那一刻的截图,见 read.md §2
e.background      # 对非激活 tab 操作的
e.opaque          # js / 坐标点击 = true,UI 标黄
```

**`hit` 和 `target` 分开是刻意的**:你说"点登录",实际命中了 `button "取消"` ——
两列摆在一起,一眼看出是认错了元素还是页面变了。

## 2. 人干的也在里面

`e.user == "human"` 的条目是人在 VNC 里点的。**这个 tab 的完整操作路径**,
不是只有你的代码干过的事。

```
14:22:03 💭 claudecode:购物车已确认,现在下单
         click "提交订单" → 命中 button "取消订单"
         → /cancel  出现『订单已取消』
14:22:06 👤 human:点了 (612,340)
```

## 3. tab 没了,记录还在

```python
old.closed        # True
old.click("x")    # TabGone
old.log()         # 照常读得到
```

被关掉、或者**被挤掉**([README §3](README.md#3-生命周期))之后,
目录还按 `WEBMUXD_TAB_KEEP` 留着。真被清了才读不到。

## 4. 保留

这个 tab 环形保留 `WEBMUXD_LOG_LIMIT` 条(默认 500),老的连截图一起删 ——
**每个 tab 各算各的**,一个话痨 tab 挤不掉别的 tab 的历史。
就是 tmux 的 `history-limit`,而 tmux 那个也是按 pane 算的。

## 5. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `tab.log(limit=, after=, only=, user=)` | `GET /api/log?tab={id}&...` |
| `tab.bundle(path)` | `GET /api/log/bundle?tab={id}` |
| `e.shot` | `GET /api/log/{seq}/shot` |

**不要拿事件流当记录用** —— 两者的区别见 [api/events.md §1](../../api/events.md#1-事件不是日志)。
