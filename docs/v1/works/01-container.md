# 01 · 容器

## 1. 一张图

```
┌─ session 容器 (webmuxd/operator) ────────────────────────────┐
│                                                             │
│  :7900 ─► sessiond ─┬─ /       查看页面(静态)             │
│                     ├─ /api/   全部 API                     │
│                     └──CDP──►  Chrome (headful,             │
│                                127.0.0.1:9222)              │
│                                     │ X11                   │
│  :6901 ─► KasmVNC ──────────────────┘                       │
│                                                             │
│  操作日志 → /data/log.jsonl + /data/shots/                  │
└─────────────────────────────────────────────────────────────┘
```

**没有 nginx,也没有转发。** 两个进程各自听自己的口:sessiond 管 API 和查看页面,
KasmVNC 管画面。查看页面把 KasmVNC 嵌成 iframe(顺手裁掉 Chrome 的 UI,见
[04 §2](04-chrome-ui-externalization.md))。

上面是**一个 session**。`webmuxd`(server)在外面管着若干个这样的容器,
见 [05](05-server-session-runtime.md)。

| 内部端口 | 用途 | 是否出容器 |
| --- | --- | --- |
| 7900 | sessiond —— 查看页面 + API | ✅ |
| 6901 | KasmVNC —— 画面 | ✅ |
| 9222 | Chrome CDP | ❌ 锁 `127.0.0.1`,永不出容器 |

查看页面和 API 同一个 origin,省掉跨域。

### 1.1 鉴权

**容器里只有一个 token,拿着 token 的人就能用。** KasmVNC 启动时给它一个,
sessiond 认 `WEBMUXD_TOKEN`,没别的。

**只读、TTL、一次性分享链接是 server 那一层的事** —— 它反正要按名字代理
`/s/<name>/`,凭证在那儿签、在那儿验([api/server.md §6](../api/server.md#6-鉴权))。
容器不掺和,也不为了"能签只读链接"去改谁转发谁。

> **一个已知后果**:裁掉 Chrome 的 tab 条和地址栏是**查看页面**那一层干的
> ([04 §2](04-chrome-ui-externalization.md)),不是容器里干的。所以**绕过查看页面、
> 直连 6901 的人,看到的是完整的 Chrome**,tab 条和地址栏都能点。
> 他制造的状态漂移靠"下次进入时对齐"收敛,见
> [api/tabs.md §5](../api/tabs.md#5-当前是哪个-tab是-sessiond-说了算)。

## 2. 起容器

```bash
docker run -d --name work \
  -p 7900:7900 -p 6901:6901 \
  --shm-size=1g \                       # 少于 1G Chrome 会崩
  -e WEBMUXD_TOKEN=changeme \              # 不设则不鉴权(仅限本机玩)
  -e WEBMUXD_VIEWPORT=1280x800 \
  -v webmuxd-work:/data \                  # 想保住登录态就挂卷
  webmuxd/operator:1.0
```

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `WEBMUXD_TOKEN` | 空 | 设了则页面和 API 都要这个 token |
| `WEBMUXD_VIEWPORT` | `1280x800` | 屏幕分辨率 = 视口 |
| `WEBMUXD_START_URL` | `about:blank` | 启动打开的页面 |
| `WEBMUXD_PROXY` | 空 | Chrome 走的代理 |
| `WEBMUXD_LOG_LIMIT` | `500` | 操作日志保留多少条(像 tmux 的 `history-limit`) |

## 3. 镜像

```dockerfile
ARG KASM_CHROME_TAG=1.16.0          # 锁 tag,别用 latest
FROM kasmweb/chrome:${KASM_CHROME_TAG}

USER root
COPY dist/sessiond    /opt/webmuxd/sessiond
COPY web/           /opt/webmuxd/web/        # 查看页面(纯静态,sessiond 自己发)
COPY startup.sh     /dockerstartup/custom_startup.sh
RUN /opt/webmuxd/sessiond/bin/pip install -r /opt/webmuxd/sessiond/requirements.txt \
 && mkdir -p /data/shots && chown -R 1000:1000 /data /opt/webmuxd \
 && chmod +x /dockerstartup/custom_startup.sh

USER 1000
EXPOSE 7900
HEALTHCHECK --interval=10s --start-period=25s CMD curl -fsS localhost:7900/healthz || exit 1
```

**要给 Chrome 加调试端口,根本不用改镜像。** kasm 的 `custom_startup.sh` 里有
`ARGS=${APP_ARGS:-$DEFAULT_ARGS}`,环境变量直接注入(实测于 `kasmweb/chromium:1.18.0`):

```bash
docker run -e APP_ARGS="--remote-debugging-port=9222 \
                        --remote-debugging-address=127.0.0.1 \
                        --disable-infobars --disable-session-crashed-bubble" ...
```

> **基座实测(2026-08-08,`kasmweb/chromium:1.18.0`)**
> - `/dockerstartup/custom_startup.sh` 存在,权限 777
> - `APP_ARGS` 环境变量可注入 Chrome 参数,**不用重建镜像**
> - `custom_startup.sh` 有 `while true` 循环,Chrome 挂了会自动重拉
> - `/dockerstartup/maximize_window.sh` **每 ~10 秒把窗口重新最大化**——
>   任何在 X 层面挪窗口的做法都会被它撤销(见 [04 §5](04-chrome-ui-externalization.md))
> - WM 是 xfwm4,默认分辨率 1024×768,Chrome 139
> - **CDP 的 Host 头校验挡掉了容器外访问**,只能容器内连——印证了 sessiond 必须跑在容器里
> - 有 `wmctrl`/`xprop`/`xwininfo`/`xwd`,**没有 `xdotool`**
>
> 换 tag 或换成 `kasmweb/chrome` 时复核这一段即可。

**不加 `--headless`**(要 GUI 才能被看见),**不用 CDP 的 `setDeviceMetricsOverride`**
—— 那会让截图和人看到的画面对不上,而"人和脚本看同一个画面"是这东西的全部意义。
视口就是屏幕分辨率。

沙箱这条得改口:**kasm 镜像自带 `--no-sandbox`**(它自己的选择,写死在 `/usr/bin/chromium`
包装脚本里),不是我们能顺手保留的。要恢复沙箱得改包装脚本并给容器相应权限,
记为已知风险。

## 4. sessiond

容器里唯一自己写的进程,几百行的量级:

```
sessiond/
├── server.py     HTTP + WS(静态页面 + 全部 API)
├── browser.py    CDP 连接、动作执行
├── observe.py    AX 树 → 元素表 → 标注截图
└── log.py        操作日志(append + 环形截断)
```

底层用 **Playwright 的 `connect_over_cdp()`**,不裸写 CDP —— 等待可见/可点击、iframe、
文件上传这些脏活它已经做对了。但 API 只暴露 webmuxd 自己的动作名,
以后想换底层不影响调用方。

## 5. 状态存哪

全在容器里的 `/data`,没有外部依赖:

| 内容 | 路径 | 挂卷后保留 |
| --- | --- | --- |
| Chrome profile(cookie / 登录态) | `/data/profile` | ✅ |
| 操作日志 | `/data/log.jsonl` | ✅ |
| 截图 | `/data/shots/` | ✅ |
| 下载文件 | `/data/downloads/` | ✅ |

不挂卷 = 容器删了全没,跟 `tmux kill-server` 一样。想留就挂 `-v`。

日志和截图按 `WEBMUXD_LOG_LIMIT` 环形截断,老的自动删,不会把磁盘撑爆 —— 就是 tmux 的 `history-limit`。

## 6. 崩了怎么办

| 情况 | 行为 |
| --- | --- |
| Chrome 崩溃 | sessiond 检测到 CDP 断开,**自动重启 Chrome**(profile 还在,页面丢失),日志记一条 `chrome_restarted` |
| sessiond 崩溃 | supervisor 拉起,Chrome 不受影响,画面照看(KasmVNC 是独立进程) |
| 容器 OOM | 容器退出;挂了卷的话 profile 和日志还在,`docker start` 回来 |

没有"unhealthy 状态机",没有 draining。崩了就重启,该丢的丢,像 tmux 里某个 pane 的进程死了一样。
