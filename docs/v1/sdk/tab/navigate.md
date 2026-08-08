# lib · Tab · 导航

**走到哪。** 都是 `Tab` 上的方法,导出成 `POST /api/tabs/{id}/...`
([api/tabs.md §3](../../api/tabs.md#3-写))。

```python
tab.goto("https://example.com/cart")
tab.back(); tab.forward()
tab.reload(); tab.reload(ignore_cache=True)
tab.stop()
tab.activate()                 # 切过去,VNC 画面随之切
tab.close()
```

## 1. `goto`

```python
tab.goto(url, wait="load", timeout=15)
```

| `wait` | 什么时候返回 |
| --- | --- |
| `none` | 发出去就返回 |
| `domcontentloaded` | DOM 解析完 |
| `load`(默认) | `load` 事件 |
| `networkidle` | 网络静默 |

打不开抛 `NavFailed`,带 `.net_error`(如 `ERR_NAME_NOT_RESOLVED`)。

**特权页面去不了**:`chrome://` `devtools://` `view-source:` 那几类抛 `BlockedURL`。
不是做不到,是不该做 —— 那些设置该在容器启动参数里配,不该让代码跑去点
([api/tabs.md §3](../../api/tabs.md#3-写))。`about:blank` 允许。

## 2. 前进后退

```python
if tab.can_go_back:            # 读内存,先判断不花钱
    tab.back()
```

**没得后退时 `back()` 抛 `BadRequest`,不静默无操作。** 这样你 UI 上按钮的禁用状态
和实际行为不会对不上。

历史列表(画"长按后退弹菜单"用的):

```python
h = tab.history()
h.entries       # [{index, url, title}, ...]
h.current       # 2
tab.goto(history_index=1)
```

`history()` **发请求**(`GET /api/tabs/{id}/history`),它不在内存里。

## 3. `activate` —— 切过去

```python
tab.activate()
```

**画面跟着切。** 一块 VNC 屏同时只显示一个 tab。

`active` 是 sessiond 记的账,不是观测出来的 —— 它改完会用 `Target.activateTarget`
把 Chrome 拽过来对齐([api/tabs.md §5](../../api/tabs.md#5-当前是哪个-tab是-sessiond-说了算))。
所以 `web.active` 立刻就是新的。

## 4. `close` —— 关掉

```python
r = tab.close()
r.created        # Tab | None
```

**永远至少留一个 tab**:关掉最后一个时 sessiond 会自动新建一个 `about:blank`,
从 `r.created` 还给你。Chrome 关掉最后一个 tab 会连窗口一起关,所以这是服务端行为,
不是 lib 的贴心([api/tabs.md §3](../../api/tabs.md#3-写))。

关掉之后句柄上的属性还能读,动作抛 `TabGone`([README §3](README.md#3-生命周期))。

## 5. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `tab.goto(url, wait=, timeout=)` | `POST /api/tabs/{id}/goto` |
| `tab.goto(history_index=)` | 同上,带 `history_index` |
| `tab.back()` `.forward()` `.reload()` `.stop()` | `POST /api/tabs/{id}/back` `/forward` `/reload` `/stop` |
| `tab.reload(ignore_cache=True)` | `{"ignore_cache": true}` |
| `tab.activate()` | `POST /api/tabs/{id}/activate` |
| `tab.close()` | `DELETE /api/tabs/{id}` |
| `tab.history()` | `GET /api/tabs/{id}/history` |

也可以走 `tab.act([{"type":"goto", ...}])` 把导航和动作串在一次往返里,
见 [input.md §3](input.md#3-act--一次往返一串动作)。
