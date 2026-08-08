# lib · 日志 · session 级(`kind="tab"` / `kind="session"`)

**不属于某一次动作的那些事。** 两类:tab 的生和死、以及整个 session 出的事。

## 1. `kind="tab"` —— tab 的生老病死

```python
for e in sess.log(kind="tab"):
    print(e.tab, e.event, e.at, e.reason, e.user)
    # t_7 opened  14:22:01  link_target_blank  human
    # t_7 closed  14:31:44  evicted            —
```

```python
e.event           # "opened" | "closed"
e.tab             # t_7
e.reason          # opened: api | link_target_blank | window_open | ctrl_click
                  #         user_ctrl_t | restored | unknown
                  # closed: api | user | evicted | crashed
e.url  e.title    # opened 时
e.final_url       # closed 时 —— 想恢复就拿它重开
e.user            # 谁弄的
```

**这是回答"这个 tab 什么时候建的、谁建的、活了多久、关的时候停在哪"的地方。**
`sess.tabs` 只有活着的;历史查这儿。

`reason == "evicted"` 是超了 tab 上限被挤掉的,不是谁的意图
([../tab/README.md §3](../tab/README.md#3-生命周期))。

## 2. `kind="session"` —— 整个 session 的事

```python
for e in sess.log(kind="session"):
    print(e.event, e.at)
    # chrome_restarted  14:40:02
    # reset             15:01:33
```

| `event` | 什么时候 |
| --- | --- |
| `session_started` | sessiond 起来了 |
| `chrome_restarted` | Chrome 崩了被自动拉起,**tab 全丢**,带 `restarts` |
| `reset` | 调了 `POST /api/reset`,清 cookie、关多余 tab |

`e.tab` 在这一类里是 `None` —— 它们不属于任何 tab。

**`chrome_restarted` 是排查时最该先看的一条**:它之后所有 tab id 都是新的,
之前的句柄全废。日志里有这条,就不用猜"为什么我的 tab 突然都不见了"。

## 3. 它们会跟着滚掉

和动作记录在**同一个文件**里,所以同一套切割规则
([README §2](README.md#2-存哪怎么切))——切到第二刀之外就没了。

tab 上限 10、一条生一条死,要靠它们填满一万行得开关五千次,
所以实际上是动作记录先滚。但**它们没有额外的保护**,这一点得知道:
真要长期留一份 tab 的生死账,自己定时 `sess.log(kind="tab")` 拉走。
