# lib · `Session`

**一个 session = 一个 kasm 容器**:一块 VNC 屏、一个 Chromium、一份日志。
从 [`Webmuxd`](manager.md) 那儿拿:

```python
sess = web.session(id="work", api_port=7900, view_port=6901)     # 新建一个
sess = web.session(id="work")     # 同一个 id → 同一个 session
```

导出成 [api/README.md](../api/README.md) 那一组 session 内的接口。
建和杀在 [manager.md](manager.md);tab 在 [tab/](tab/);日志在 [log/](log/)。

## 1. 一个 session 两个口

```python
sess.view_url          # 画面(KasmVNC),拿去浏览器里看或塞进 iframe
sess.api_url          # API 的 base
sess.name  sess.runtime  sess.state       # starting | ready | dead | unreachable
sess.port                                 # API 那个口
sess.created_at
sess.handle                               # {"container_id": ...} 或 {"display":..., "pids":...}
```

**两个口各干各的**([works/01 §1](../works/01-container.md#1-一张图)):
6901 那个是干净的 KasmVNC,7900 那个是 webmuxd 的 API。
裁掉 Chromium 自带的 tab 条是**你嵌 iframe 时做的**
([works/04 §2](../works/04-chrome-ui-externalization.md))。

**这是和 tmux 差别最大的一处**:tmux 一个 socket 复用所有 session,kasm 不行 ——
每个 session 自带一块屏,端口没法复用([works/05 §2](../works/05-server-session-runtime.md#2-对照表))。

## 2. 在它上面能干什么

```python
tab = sess.open("https://shop.example.com")   # 开 tab,见 tab/
sess.tabs   sess.active                       # 读内存,见 README §3
sess.log()  sess.bundle("out.zip")            # 日志,见 log/

sess.status()         # Chromium 活着没、版本、busy
sess.viewport()       # 屏幕尺寸和 crop_top
sess.reset()          # 清 cookie、关多余 tab、回 about:blank
sess.kill()           # 停掉自己
```

**页面动作不挂在这儿**,挂在 `Tab` 上 —— `sess.click(...)` 这种方法**故意不给**:
一个 session 有多个 tab,"在哪个 tab 上点"不该靠隐式的当前值。

## 3. 分享链接

```python
sess.view_url                                    # 你自己看,完整权限
r = sess.share()                                # 给别人,默认只读,1 小时
r.view_url, r.api_url                           # 两个 URL,画面和 API
sess.share(writable=True, ttl=3600)             # 可操作 —— 能碰你所有登录态
```

`share()` **默认 `read_only=True`**,和 API、CLI、ttyd 的默认一致。
lib 不做"代码里方便所以更宽松"这种事。

只读链接能看画面、能读 `GET`,所有写操作在对面返回 `403 read_only`。

## 4. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `sess.status()` | `GET /api/status` |
| `sess.viewport()` | `GET /api/viewport` |
| `sess.reset()` | `POST /api/reset` |
| `sess.kill()` | `DELETE /api/sessions/{name}` |
| `sess.share(writable=, ttl=)` | `POST /api/live-token` `{read_only, ttl_s}` |
| `sess.view_url` `sess.api_url` | `/s/{name}/vnc/` `/s/{name}/api/`,或直连两个端口 |
| `sess.name` `sess.runtime` `sess.state` `sess.handle` | `GET /api/sessions/{name}` 的字段 |
| `sess.open()` `sess.tabs` `sess.log()` | 见 [tab/](tab/) 和 [log/](log/) |

建、列、杀在 [manager.md §4](manager.md#5--api-对照)。
