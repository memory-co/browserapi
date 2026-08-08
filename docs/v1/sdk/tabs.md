# SDK · tab

对应 [api/tabs.md](../api/tabs.md)。

## 1. 列出和操作

```python
for t in b.tabs():
    print(t.index, t.title, t.url, "●" if t.active else "")

t = b.new_tab("https://example.com")
t.goto("https://example.com/cart")
t.back(); t.reload()
t.activate()
t.close()

b.reorder(["t_7", "t_3"])          # 少给的自动排在后面,不用凑全排列
```

`b.tab(x)` 按 id、index 或标题拿一个:

```python
b.tab("t_7")        # id
b.tab(2)            # index
b.tab(title="购物车")  # 唯一匹配才行,否则抛 NotFound 带 .candidates
```

按标题找是**客户端**干的(先 `b.tabs()` 再本地匹配),API 只认 id ——
和 CLI 的 `-t work:购物车` 是同一套规则。

## 2. `Tab` 对象

字段就是 [api/tabs.md §1](../api/tabs.md#1-tab-对象) 的 Tab,原样映射成属性:

```python
t.id  t.index  t.active  t.url  t.title  t.loading
t.security  t.can_go_back  t.can_go_forward
t.favicon        # → bytes,懒加载;拿不到时是 None
t.opener  t.created_at  t.crashed
```

`t.favicon` 是**唯一一个不直接映射的字段**:API 给的是 URL,SDK 访问时才去取字节,
取到之后缓存。想要 URL 就用 `t.favicon_url`。

`Tab` 是取回来那一刻的**快照**,不会自己更新。要跟着变就订阅事件
([events.md](events.md)),或者重新 `b.tabs()`。

## 3. 跨 tab 操作

`Tab` 对象上能直接调页面动作,等价于给 `act` 带 `tab` 参数:

```python
b.tab("t_7").click("确认")       # 对非激活 tab 也有效,但人在画面上看不见
b.tab("t_7").observe()
b.tab("t_7").text()
```

这类动作在日志里标 `background: true`
([api/README §2](../api/README.md#2-一条贯穿全局的规则tab-参数))。

## 4. 历史

```python
h = b.tab("t_3").history()
h.entries       # [{index, url, title}, ...]
h.current       # 2
b.tab("t_3").goto(history_index=1)
```

给"长按后退弹历史"用的。终端里用不上,所以 [CLI 没有对应命令](../cli/tabs.md#5--api-对照)。

## 5. 关最后一个 tab

```python
r = b.tab("t_9").close()
r.created        # Tab | None —— 关的是最后一个时,自动新建的 about:blank
```

**永远至少留一个 tab**,这是服务端行为([api/tabs.md §3](../api/tabs.md#3-写)),
SDK 只是把新建的那个还给你。

## 6. ↔ API 对照

| SDK | API |
| --- | --- |
| `b.tabs()` | `GET /api/tabs` |
| `b.tab(id)` | `GET /api/tabs/{id}` |
| `b.tab(title=)` `b.tab(index)` | 客户端匹配,不是 API 行为 |
| `b.new_tab(url, active=, index=, opener=)` | `POST /api/tabs` |
| `t.activate()` | `POST /api/tabs/{id}/activate` |
| `t.close()` | `DELETE /api/tabs/{id}` |
| `t.goto(url, wait=, timeout=)` | `POST /api/tabs/{id}/goto` |
| `t.goto(history_index=)` | 同上,带 `history_index` |
| `t.back()` `t.forward()` `t.reload()` `t.stop()` | `POST /api/tabs/{id}/...` |
| `t.history()` | `GET /api/tabs/{id}/history` |
| `t.favicon` / `t.favicon_url` | `GET /api/tabs/{id}/favicon` |
| `b.reorder([...])` | `POST /api/tabs/reorder` |
| `t.click()` `t.observe()` … | `POST /api/act` / `GET /api/observe` 带 `tab` |

**对不上的两处**,都是客户端便利:`b.tab(title=)` / `b.tab(index)` 的匹配,
以及 `reorder` 允许只给部分顺序(API 要求完整排列,SDK 帮你补齐再发)。
