# lib · tab

导出成 [api/tabs.md](../api/tabs.md)。

**tab 是句柄,状态在内存里。** 这两条是 lib 和 HTTP 差别最大的地方,
先看 [README §2](README.md#2-tab-是句柄不是当前-tab) 和 [§3](README.md#3-tab-的状态在内存里)。

## 1. 拿句柄

```python
tab = web.open("https://shop.example.com")     # 新建 + 导航 + 返回句柄

web.tabs                       # [Tab],按 index 排好
web.active                     # 当前那个
web.tab("t_7")                 # 按 id
web.tab(2)                     # 按 index
web.tab(title="购物车")         # 按标题,唯一匹配才行,否则抛 NotFound 带 .candidates
```

**这几个都不发请求** —— 表在内存里。按标题匹配也是本地做的,线上只认 id。

`web.open()` 收了 `POST /api/tabs` 和 `POST /api/tabs/{id}/goto` 两次调用,
因为「开个新标签页去某个网址」本来就是一件事。想只开不导航就 `web.open()` 不给 url。

## 2. 句柄上能干什么

```python
tab.goto("https://example.com/cart")
tab.back(); tab.forward(); tab.reload(); tab.stop()
tab.activate()                 # 切过去,VNC 画面随之切
tab.close()

tab.click("登录", user="claudecode")
tab.type("手机号", "13800000000")
tab.observe()
tab.text()
```

页面动作见 [agent.md](agent.md)。**对非激活 tab 操作是可以的**,
但 VNC 画面只显示激活的那个,所以人看不见,日志里标 `background: true`。

### 关最后一个

```python
r = tab.close()
r.created        # Tab | None —— 关的是最后一个时,自动新建的 about:blank
```

**永远至少留一个 tab**,这是服务端行为([api/tabs.md §3](../api/tabs.md#3-写)) ——
Chrome 关掉最后一个会连窗口一起关。lib 只是把新建的那个还给你。

### 后退不动就抛

```python
tab.back()      # 没得后退 → BadRequest
```

不静默无操作。`tab.can_go_back` 在内存里,先判断也不花钱。

## 3. 属性:读内存

```python
tab.id  tab.index  tab.active  tab.url  tab.title  tab.loading
tab.security  tab.can_go_back  tab.can_go_forward
tab.opener  tab.created_at  tab.crashed
```

字段就是 [api/tabs.md §1](../api/tabs.md#1-tab-对象) 的 Tab 对象,
**但它不是快照** —— 句柄一直活着,值跟着事件流走:

```python
tab = web.open("https://shop.example.com")
tab.click("登录")
print(tab.url)          # 已经是 /login 了,不用重新取
```

`click()` 的响应里带 `after.url`,lib 直接回灌内存,所以这里没有竞态
([README §3](README.md#3-tab-的状态在内存里))。

`tab.favicon` 是唯一一个**惰性发请求**的属性:事件流里只带 URL 不带字节,
访问时才去取,取到后缓存。要 URL 就用 `tab.favicon_url`。

tab 被关掉之后,句柄上的属性还能读(最后一次的值),但任何动作抛 `TabGone`。
`tab.closed` 告诉你它还在不在。

## 4. 新 tab 是怎么冒出来的

页面自己开的 tab(`target=_blank`、`window.open()`),或者人在 VNC 里 Ctrl+T ——
事件带 `reason`,lib 原样给你([api/tabs.md §4](../api/tabs.md#4-事件)):

```python
for e in web.watch("tab.created"):
    print(e.tab.title, e.reason)     # api | link_target_blank | window_open
                                     # ctrl_click | user_ctrl_t | restored
```

点出来的新 tab 也能当场拿到,不用等事件:

```python
r = tab.click("查看帮助")
new = r.new_tabs[0]        # Tab 句柄
new.click("联系客服")
new.close()
```

一串动作里要连着操作新 tab,用 `$new` 占位符走一次 `act()`,省往返 ——
见 [agent.md §2](agent.md#2-做tabact-和快捷方法)。

## 5. 排序

```python
web.reorder(["t_7", "t_3"])    # 少给的自动排在后面
```

线上要求是当前全部 tab 的一个完整排列,lib 帮你补齐再发。

## 6. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `web.tabs` `web.active` `tab.<属性>` | **不请求** —— 内存,由 `WS /api/events` 维护 |
| `web.tab(title=)` `web.tab(index)` | 本地匹配,线上只认 id |
| `web.sync()` | `GET /api/tabs` + `GET /api/status` |
| `web.open(url)` | `POST /api/tabs` + `POST /api/tabs/{id}/goto` |
| `tab.activate()` | `POST /api/tabs/{id}/activate` |
| `tab.close()` | `DELETE /api/tabs/{id}` |
| `tab.goto(url, wait=, timeout=)` | `POST /api/tabs/{id}/goto` |
| `tab.goto(history_index=)` | 同上,带 `history_index` |
| `tab.back()` `.forward()` `.reload()` `.stop()` | `POST /api/tabs/{id}/...` |
| `tab.history()` | `GET /api/tabs/{id}/history` |
| `tab.favicon` / `tab.favicon_url` | `GET /api/tabs/{id}/favicon` |
| `web.reorder([...])` | `POST /api/tabs/reorder` |
| `tab.click()` `tab.observe()` … | `POST /api/act` / `GET /api/observe` 带 `tab` |

**没导出去的**:句柄本身、内存里那份表、按标题/index 找、`reorder` 补齐。
其中「句柄」是最大的一处 —— 线上没有句柄,只有 `{id}` 和「不传就当前 tab」那条规则。
