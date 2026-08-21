# lib · 日志 · 动作(`kind="action"`)

**谁在哪个 tab 上做了什么。** 日志里绝大多数是这一类。

```python
for e in tab.log(limit=50, only="failed"):
    print(e.seq, e.at, e.user, e.note, e.action, e.hit, e.ok, e.after.changed)

tab.bundle("t_7.zip")     # 这个 tab 的记录 + 截图 + 离线 HTML
```

`tab.log()` 就是 `sess.log(tab=tab.id)` —— **按 tab 过滤,不是读单独的文件**
([README §3](README.md#3-按-tab-读就是过滤))。

## 1. 一条长什么样

```python
e.seq             # 全局单调,和事件流共用一个计数器
e.at
e.kind            # "action"
e.tab             # 哪个 tab
e.user            # 署名
e.note            # act() 传的那句思考
e.action          # click / type / goto ...
e.target          # 你给的定位:{"text": "登录"}
e.hit             # 实际命中的:role / name / bbox
e.ok  e.ms
e.after.url  e.after.changed     # 「出现『订单已取消』」
e.shot            # 那一刻的截图,见 ../tab/read.md §2
e.background      # 对非激活 tab 操作的
e.opaque          # js / 坐标点击 = true,UI 标黄
```

## 2. `target` 和 `hit` 分开是刻意的

你说"点登录",实际命中了 `button "取消"` —— **两列摆在一起,一眼看出是认错了元素
还是页面变了**。只记一个就没法判断。

失败的那条带 `candidates`,和当时返回给调用方的是同一份。

## 3. 人干的也在里面

`e.user == "human"` 的是人在 VNC 里点的。所以这是**这个 tab 的完整操作路径**,
不是只有你的代码干过的事([README §4](README.md#4-这是完整的操作路径))。

## 4. tab 没了,记录还在

```python
old.closed        # True
old.click("x")    # TabGone
old.log()         # 照常读得到
```

被关掉、或者**被挤掉**([../tab/README.md §3](../tab/README.md#3-生命周期))之后,
它的条目还在同一个 `log.jsonl` 里,直到被切掉那一刀带走。

想知道它是怎么没的,查 [session.md](session.md)。
