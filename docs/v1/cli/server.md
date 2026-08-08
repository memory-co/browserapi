# CLI · 会话与 server

对应 [api/server.md](../api/server.md)。管的是**有哪些 session**,
不是某个浏览器里发生什么(那是 [act.md](act.md) / [tabs.md](tabs.md) / [log.md](log.md))。

## 1. 命令

```bash
webmuxd new [-s NAME] [--runtime R] [-p PORT] [-u URL] [-v WxH]
            [--volume VOL] [--proxy URL] [--endpoint URL] [-d]
webmuxd ls
webmuxd attach -t NAME [-p]
webmuxd share  -t NAME [--writable] [--ttl 1h]
webmuxd kill   -t NAME
webmuxd rename -t NAME NEW
webmuxd has    -t NAME

webmuxd start-server
webmuxd kill-server
webmuxd server --listen 0.0.0.0:7800
webmuxd info
```

## 2. 会话

```console
$ webmuxd new -s work
work  →  http://localhost:7900

$ webmuxd new -s scrape -u https://example.com
scrape  →  http://localhost:7901

$ webmuxd ls
work    container  7900  3 tabs  shop.example.com/cart   ●
dev     process    7901  1 tab   localhost:3000
prod    remote     -     5 tabs  intranet.corp/dash
stale   process    7903  dead — webmuxd kill -t stale 清掉

$ webmuxd attach -t work        # 自己看,完整权限,用默认浏览器打开画面
$ webmuxd attach -t work -p     # 只打印 URL,不开浏览器(无 GUI 环境用)
http://localhost:7800/s/work/vnc/

$ webmuxd share -t work         # 给别人的链接,默认只读(抄 ttyd)
http://localhost:7800/s/work/vnc/?t=...   (只读,1 小时后过期)

$ webmuxd share -t work --writable
http://localhost:7800/s/work/vnc/?t=...   (可操作,1 小时后过期)
⚠ 这个链接能操作你的浏览器,包括已登录的站点
```

- `-p PORT` 不给就自动从 7900 往上找空闲端口。**一个 session 一个端口**,
  kasm 复用不了 —— 这是和 tmux 差别最大的一处([works/05 §2](../works/05-server-session-runtime.md))
- `-d` 建完不 attach(默认就是不 attach,`-d` 只是为了跟 tmux 的手感一致)
- **detach 不需要命令**——关掉网页就是 detach,容器照跑
- `has` 只返回退出码,给脚本用:`webmuxd has -t work || webmuxd new -s work`
- `attach` 是**你自己看**,走 socket 鉴权,完整权限
- `share` 是**给别人**,签一次性 token。**默认只读**,和 ttyd 的默认一致;
  要可操作得显式 `--writable`,并且会打印一行警告

`ls` 的那一列 `state` 是**现场探活**的结果,不是读缓存
([api/server.md §3](../api/server.md#3-session-管理))。所以 `dead` 就是真的死了,
不是记录过期。

## 3. runtime

session 怎么被拉起来,创建时选一次,之后所有命令都一样:

```bash
webmuxd new -s work                                     # container(默认)
webmuxd new -s dev  --runtime process                   # 不要 docker,秒起,没隔离
webmuxd new -s prod --runtime remote \
                   --endpoint https://browser.internal:7800
```

```conf
# ~/.webmuxd.conf
set -g runtime container
```

docker 不可用又没给 `--runtime` 时**报错,不静默降级**
(对应 `503 runtime_unavailable`,退出码 1):

```console
$ webmuxd new -s work
✗ runtime_unavailable: docker 不可用
  可以改用 --runtime process,但那样没有隔离(页面跑在你自己机器上)
```

这行提示来自 `GET /api/server` 的 `runtimes` 探测结果,所以它说得准。

## 4. socket

和 tmux 一样,**server 按需自启,你几乎不会直接碰它**。
`start-server` 有这个命令,但基本用不到。

```bash
webmuxd -L ci new -s build                # 换个 socket = 另一套互不可见的 server
webmuxd -S /tmp/x.sock ls
```

socket 在 `$XDG_RUNTIME_DIR/webmuxd/default.sock`,靠文件权限(0600)鉴权,
**走 socket 不需要 token**([api/server.md §6](../api/server.md#6-鉴权))。

## 5. `kill-server` 之后会怎样

**取决于 runtime,这点必须知道:**

| session 的 runtime | `kill-server` 之后 |
| --- | --- |
| `process` | **跟着死**(是 server 的子进程,和 tmux 的 pane 一样) |
| `container` | **活着**,server 重启后自动重新接管 |
| `remote` | **活着**,本来就不归它管 |

所以 `webmuxd ls` 一定会显示 runtime 那一列 —— 不然你不知道自己的 session 抗不抗得住重启。

## 6. 远端

```bash
webmuxd -H https://browser.internal:7800 ls
export WEBMUXD_HOST=https://browser.internal:7800
export WEBMUXD_TOKEN=...
```

`-H` 指向的是**一个远端 server**(不是单个 session),所以 `new` / `ls` / `kill`
这些会话级命令**照常可用**——由那边的 server 执行。

这是相对早先设计的一个改进:以前 `-H` 指向单个容器,会话级命令就没法用了。

对面必须是 TCP 监听的 server,而绑 `0.0.0.0` **没设 `WEBMUXD_TOKEN` 时拒绝启动**
([api/server.md §1](../api/server.md#1-两个监听))——那是把一个能操作浏览器、
而且很可能带着登录态的东西放到网上。

## 7. ↔ API 对照

| CLI | API |
| --- | --- |
| `new -s NAME --runtime R -u URL -p PORT -v WxH --volume V --proxy P --endpoint E` | `POST /api/sessions` `{name, runtime, url, port, viewport, volume, proxy, endpoint}` |
| `ls` | `GET /api/sessions` |
| `has -t NAME` | `GET /api/sessions/{name}` → 退出码 3 |
| `rename -t NAME NEW` | `POST /api/sessions/{name}/rename` |
| `kill -t NAME` | `DELETE /api/sessions/{name}` |
| `attach -t NAME` | 打开 `/s/{name}/vnc/`,不调管理接口 |
| `share -t NAME [--writable] [--ttl]` | `POST /api/sessions/{name}/live-token` `{read_only, ttl_s}` |
| `info` | `GET /api/server` |
| `kill-server` | `POST /api/server/shutdown` |
| `-L` / `-S` | 换 socket,不经 HTTP |
| `-H URL` | 把上面所有调用发到那个 server |

`share --writable` 就是 `read_only: false`;不加 `--writable` 就是 `true`。
CLI 的默认值和 API 的默认值**故意一致**,不做"CLI 更方便所以更宽松"这种事。
