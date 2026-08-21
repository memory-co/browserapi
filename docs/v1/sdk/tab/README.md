# lib · Tab

**`Tab` 是这个库唯一的操作对象。** 打开一个网址拿到句柄,之后所有事都在句柄上做 ——
导航、点击、观测,全部。没有别的"操作器"、"控制器"、"agent" 之类的东西。

```python
tab = sess.open("https://shop.example.com")
tab.click("登录")
print(tab.url, tab.title)
```

分门别类:

| 文件 | 管什么 | 方法 |
| --- | --- | --- |
| README.md(本文) | 拿句柄、读属性、生命周期 | `sess.open` `sess.tab` `sess.tabs` `tab.url` … |
| [navigate.md](navigate.md) | **走到哪** | `goto` `back` `forward` `reload` `stop` `activate` `close` `history` |
| [input.md](input.md) | **往里做** | `click` `type` `key` `select` `check` `scroll` `upload` `wait_for` `js` `act` |
| [read.md](read.md) | **往外看** | `screenshot` `text` `extract` |

这个 tab 干过什么在 [../log/tab.md](../log/tab.md),它怎么生怎么死在
[../log/session.md](../log/session.md) —— 日志不分 tab,是一个文件筛出来的
([../log/README.md](../log/README.md))。

## 1. 拿句柄

```python
tab = sess.open("https://shop.example.com")     # 新建 + 导航 + 返回句柄
                                               # 超上限时会挤掉最不活跃的,见 §3

sess.tabs                       # [Tab],按 index 排好
sess.active                     # 当前那个
sess.tab("t_7")                 # 按 id
sess.tab(2)                     # 按 index
sess.tab(title="购物车")         # 按标题,唯一匹配才行,否则抛 NotFound 带 .candidates
```

**这几个都不发请求** —— 表在内存里(§2)。按标题、按 index 找也是本地做的,线上只认 id。

`sess.open()` 就是 `POST /api/tabs {url}` 一次请求 —— 建 tab 和导航在线上本来就是一步
([works/06 §1](../../works/06-tab-sync.md#1-in--sessopenhttpsshopexamplecom))。
想只开不导航就不给 url。

**lib 这层没有"当前 tab"这条规则。** 线上有(不传 `tab` 参数就作用在激活的那个),
因为 HTTP 没有句柄;这边你手里本来就攥着一个。

## 2. 属性:读内存,不发请求

```python
tab.id  tab.index  tab.active  tab.url  tab.title  tab.loading
tab.security  tab.can_go_back  tab.can_go_forward
tab.opener  tab.reason  tab.created_at  tab.crashed
tab.dialog        # 有弹窗挡着时不是 None,见 navigate.md §5
```

字段就是 [api/tabs.md §1](../../api/tabs.md#1-tab-对象) 的 Tab 对象,
**但它不是快照** —— 句柄一直活着,值跟着事件流走:

```python
tab = sess.open("https://shop.example.com")
tab.click("登录")
print(tab.url)          # 已经是 /login 了,不用重新取
```

`click()` 的响应里带 `after.url`,lib 直接回灌内存,所以这里没有竞态
([../README.md §3](../README.md#3-tab-的状态在内存里))。

**唯一惰性发请求的属性是 `tab.favicon`**:事件流里只带 URL 不带字节,
访问时才去取,取到后缓存。要 URL 用 `tab.favicon_url`。

## 3. 生命周期

```python
tab.closed        # 还在不在
tab.close()
```

tab 没了之后,句柄上的**属性还能读**(最后一次的值),但**任何动作抛 `TabGone`**。
这是有意的:回看一个已经关掉的 tab 最后停在哪,是常见需求。

### 它可能不是你关的

**同时最多 `WEBMUXD_TAB_MAX` 个 tab(默认 10),超了会挤掉最不活跃的那个** ——
按"最后一次被激活或被操作"排。当前激活的、正在跑动作的不会被挤。

所以**你手里的句柄可能在你脚下死掉**:

```python
try:
    old_tab.click("确认")
except TabGone as e:
    if e.reason == "evicted":            # 不是你关的,是被挤的
        tab = sess.open(e.final_url)      # 想恢复就自己重开
```

被挤掉的 tab **记录还在**:`tab.log()` 照样读得到,`sess.log(kind="tab")` 里
有它的建和关 —— 直到被切掉那一刀带走([../log/README.md §2](../log/README.md#2-存哪怎么切))。

开着的 tab 越多,内存和磁盘越吃 —— 上限就是为这个设的
([works/03 §7](../../works/03-log.md#5-保留))。

`tab.id` 关掉之后**不复用** —— 日志和历史观测里的 `t_7` 永远指同一个东西
([works/06 §1](../../works/06-tab-sync.md#1-in--sessopenhttpsshopexamplecom))。

## 4. 跨 tab

句柄互相独立。**输入类**的动作对非激活 tab 直接可用:

```python
sess.tab("t_7").click("确认")      # 人在画面上看不见,日志里标 background: true
```

CDP 的输入投递给 target,不走屏幕焦点。但 VNC 画面只显示激活的那个。

**要像素就不行** —— Chromium 不渲染后台 tab,所以 `screenshot()`
会先把那个 tab 切到前台,画面会跳。见 [read.md §3](read.md#3-要像素就得切到前台)。

## 5. 新 tab 从哪来

页面自己开的(`target=_blank`、`window.open`)、人按 Ctrl+T ——
都会进 `sess.tabs`,并带 `reason` 说明来路
([api/tabs.md §4](../../api/tabs.md#4-事件)):

```python
for e in sess.log(kind="tab"):
    print(e.tab, e.event, e.reason)  # api | page | user | restored
```

自己点出来的不用等事件,当场就有:

```python
r = tab.click("查看帮助")
new = r.new_tabs[0]        # Tab 句柄
```

带尺寸参数的 `window.open` 在浏览器里本会开成窗口,webmuxd **一律转成 tab**,
所以这里只会有 tab([works/07](../../works/07-popup-windows.md))。

## 6. 排序

```python
sess.reorder(["t_7", "t_3"])    # 少给的自动排在后面,lib 帮你补齐再发
```

顺序是 sessiond 自己维护的一个列表,不进 Chromium —— CDP 没有挪 tab 的命令
([works/06 §4](../../works/06-tab-sync.md#4-剩下那些字段从哪来))。

## 7. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `sess.tabs` `sess.active` `tab.<属性>` | **不请求** —— 内存,由 `WS /api/events` 维护 |
| `sess.tab(title=)` `sess.tab(index)` | 本地匹配,线上只认 id |
| `sess.sync()` | `GET /api/tabs` + `GET /api/status` |
| `sess.open(url)` | `POST /api/tabs {url}` |
| `sess.reorder([...])` | `POST /api/tabs/reorder` |
| `tab.favicon` / `tab.favicon_url` | `GET /api/tabs/{id}/favicon` |
| `tab.closed` | 客户端状态 |

导航见 [navigate.md](navigate.md),动作见 [input.md](input.md),观测见 [read.md](read.md)。
