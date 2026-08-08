# server 管理接口

server 持有全部 session,概念见 [works/05](../works/05-server-session-runtime.md)。
这里是它对外的两组接口。

**和 session 自己的 `/api/*`([README](README.md))是两回事**:
- server 的接口管**有哪些 session**
- session 的接口管**那个浏览器里发生什么**

## 1. 两个监听

server 同时扮演 tmux 的 server(控制 socket)和 ttyd(HTTP 暴露),
所以**两个都开着**——[works/05 §1](../works/05-server-session-runtime.md)。

| | 地址 | 默认 | 用途 |
| --- | --- | --- | --- |
| 控制 socket | `$XDG_RUNTIME_DIR/webmuxd/default.sock` | 开 | CLI 走这个,不占端口,靠文件权限(0600) |
| HTTP | `127.0.0.1:7800` | **开** | 管理 + 按名字代理到各 session 的两个口 |

socket 和 tmux 一致:`-L name` 换名字、`-S /path` 指定路径,不同 socket 的 server 互不可见。

**HTTP 不是可选项**:画面本身就是网页,不经它就得把每个 session 的两个端口
全暴露出去。所以问题不是"要不要开",而是**绑在哪**:

```bash
webmuxd server                            # 127.0.0.1:7800,只有本机
webmuxd server --listen 0.0.0.0:7800      # 对外,必须有 WEBMUXD_TOKEN
```

绑到 `0.0.0.0` **没设 `WEBMUXD_TOKEN` 时拒绝启动**,不给"待会再加"的机会。
这是整个系统里最需要谨慎的一步:那是把一个能操作浏览器、
而且很可能带着登录态的东西放到网上。

## 2. 代理

TCP 开了之后,一个地址通到所有 session:

每个 session 有**两个口**([works/01 §1](../works/01-container.md#1-一张图)),
server 把它们并到一个地址下:

```
GET  http://host:7800/s/work/vnc/        → session work 的 KasmVNC(:6901)
GET  http://host:7800/s/work/api/tabs    → session work 的 GET /api/tabs(:7900)
```

**`/s/<name>/api/` 之后的部分原样转发**,所以 [README](README.md)、[tabs.md](tabs.md)、
[act.md](act.md)、[log.md](log.md) 里的一切都直接适用,只是前面多一段。
`/s/<name>/vnc/` 是 KasmVNC 原样的东西,我们不碰。

**上层拿到的就是这两个 URL**:一个塞进 iframe 当画面(自己按 `crop_top` 裁,
见 [works/04 §2](../works/04-chrome-ui-externalization.md)),一个用来调 API。

session 自己的两个端口仍然直连得到,但走 server 只用开一个口。

## 3. session 管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/sessions` | 列表 |
| `POST` | `/api/sessions` | 新建 |
| `GET` | `/api/sessions/{name}` | 单个 |
| `DELETE` | `/api/sessions/{name}` | 停掉 |
| `POST` | `/api/sessions/{name}/rename` | 改名 |
| `GET` | `/api/server` | server 自己的状态 |
| `POST` | `/api/server/shutdown` | 等价 `kill-server` |

### `GET /api/sessions`

```jsonc
{ "sessions": [
  { "name": "work", "runtime": "container", "state": "ready",
    "endpoint": "http://127.0.0.1:7900",
    "proxy": "/s/work/",
    "tab_count": 3, "active_tab_url": "https://shop.example.com/cart",
    "created_at": "2026-08-08T14:20:11Z",
    "handle": { "container_id": "6d1b21f4cc07" } },

  { "name": "dev", "runtime": "process", "state": "ready",
    "endpoint": "http://127.0.0.1:7901", "proxy": "/s/dev/",
    "tab_count": 1, "active_tab_url": "http://localhost:3000",
    "handle": { "display": ":7", "pids": {"xvnc":4821,"chrome":4830,"sessiond":4835} } },

  { "name": "stale", "runtime": "process", "state": "dead",
    "endpoint": null, "hint": "webmuxd kill -t stale 清掉" }
] }
```

`state`:`starting` / `ready` / `dead` / `unreachable`(remote 探不到)。

**每次请求都现场探活**,不是读缓存——文件只是线索,`alive()` 才是真相
([works/05 §6](../works/05-server-session-runtime.md))。

### `POST /api/sessions`

```jsonc
{ "name": "work",                     // 不给则自动生成,像 tmux 的 0/1/2
  "runtime": "container",             // container | process | remote
  "url": "https://example.com",       // 启动打开的页面
  "viewport": "1280x800",
  "port": 7900,                       // 不给则自动找空闲
  "proxy": "http://egress:3128",
  "volume": "webmuxd-work",            // container 专用
  "endpoint": "https://..." }         // remote 专用
```
→ `201`

```jsonc
{ "name": "work", "runtime": "container", "state": "ready",
  "endpoint": "http://127.0.0.1:7900", "proxy": "/s/work/",
  "vnc_url": "http://host:7800/s/work/vnc/",
  "api_url": "http://host:7800/s/work/api/" }
```

**runtime 不可用时报错,不降级**:

```jsonc
{ "error": { "code": "runtime_unavailable",
             "message": "docker 不可用",
             "details": { "runtime": "container",
                          "hint": "改用 runtime=process,但那样没有隔离" } } }
```

### `DELETE /api/sessions/{name}`

停掉并清理。`remote` runtime **只删本地记录,不动对面**,响应里会说明:

```jsonc
{ "name": "prod", "removed": true, "note": "remote session,对面仍在运行" }
```

### `GET /api/server`

```jsonc
{ "version": "1.0",
  "socket": "/run/user/1000/webmuxd/default.sock",
  "listen": "0.0.0.0:7800",
  "started_at": "...", "uptime_s": 8241,
  "sessions": { "total": 3, "ready": 2, "dead": 1 },
  "runtimes": { "container": true, "process": true, "remote": true },
  "default_runtime": "container" }
```

`runtimes` 是**探测结果**(docker 通不通、Xvnc 装没装),CLI 用它给出准确的报错提示。

## 4. 事件

```
WS /api/events
```

server 级事件,和 session 内部那条同步流([works/06 §5](../works/06-tab-sync.md#5-推给客户端))分开:

| type | 什么时候 |
| --- | --- |
| `session.created` | 新 session 起来了 |
| `session.ready` | 探活通过,可以用了 |
| `session.died` | 进程/容器没了 |
| `session.adopted` | server 重启后重新接管了一个容器 session |
| `server.shutdown` | 要关了 |

## 5. 错误

沿用 [README §4](README.md#4-错误) 的形状,多这几个:

| code | HTTP | 意思 |
| --- | --- | --- |
| `session_not_found` | 404 | 没这个名字 |
| `session_exists` | 409 | 重名 |
| `runtime_unavailable` | 503 | 这个 runtime 起不来,带 `hint` |
| `no_port` | 503 | 端口范围用完了 |
| `session_dead` | 410 | 记录还在但探活失败,提示清理 |

## 6. 鉴权

| 走哪 | 怎么鉴权 |
| --- | --- |
| unix socket | 文件权限(0600,只有你自己)。**不需要 token** |
| TCP 管理接口 | `Authorization: Bearer $WEBMUXD_TOKEN` |
| TCP 代理 `/s/<name>/` | 同上,或该 session 的一次性 view token |

**观看链接用一次性 token**,由 `POST /api/sessions/{name}/live-token` 签发
(和 session 级的 `/api/live-token` 同一个东西,只是从 server 这边要):

```jsonc
{ "read_only": true, "ttl_s": 3600 }
→ { "vnc_url": "http://host:7800/s/work/vnc/?t=...",
    "api_url": "http://host:7800/s/work/api/",
    "expires_at": "..." }
```

`read_only` 的链接能看画面、能读 `GET`,所有写操作返回 `403 read_only`。
发给别人看的时候用这个。
