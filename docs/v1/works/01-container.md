# 01 · 容器

## 1. 一张图

```
┌─ session 容器 (webmuxd/operator) ────────────────────────────┐
│                                                             │
│  :6901 ─► KasmVNC ──── X11 ────┐                            │
│                                │                            │
│  :7900 ─► sessiond ──── CDP ──►┴─ Chromium (headful,          │
│                                   127.0.0.1:9222)           │
│                                                             │
│  日志 → /data/log.jsonl + /data/shots/                      │
└─────────────────────────────────────────────────────────────┘
```

**两个口,各干各的:**

| 口 | 是什么 | 出容器 |
| --- | --- | --- |
| 6901 | **干净的 KasmVNC** —— 画面,人可以直接用鼠标键盘 | ✅ |
| 7900 | **webmuxd 的 API** —— 程序化操作和日志 | ✅(不需要就别开) |
| 9222 | Chromium CDP | ❌ 锁 `127.0.0.1`,永不出容器 |

**没有 nginx,没有转发,也没有我们自己的查看页面。**
画面怎么摆、tab 条长什么样、日志怎么显示,**上层自己组织** ——
我们只负责把干净的画面和干净的 API 摆出来。

6901 那个口就是 kasm 原样的东西:**不开 7900,它就是一个能用浏览器看的 Chromium**;
开了 7900,它才是 webmuxd。

裁掉 Chromium 自带的 tab 条和地址栏是**上层嵌进 iframe 时做的**
([04 §2](04-chrome-ui-externalization.md))—— 所以**直连 6901 看到的是完整的 Chromium**,
这是正常的,不是漏了什么。

上面是**一个 session**。`webmuxd`(server)在外面管着若干个这样的容器,
见 [05](05-server-session-runtime.md)。

### 1.1 鉴权

**容器里只有一个 token,拿着 token 的人就能用。** KasmVNC 启动时给它一个,
sessiond 认 `WEBMUXD_TOKEN`,没别的。

**只读、TTL、一次性分享链接是 server 那一层的事** —— 它反正要按名字代理
`/s/<id>/`,凭证在那儿签、在那儿验([api/server.md §6](../api/server.md#6-鉴权))。

## 2. 起容器

```bash
docker run -d --name work \
  -p 7900:7900 -p 6901:6901 \
  --shm-size=1g \                       # 少于 1G Chromium 会崩
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
| `WEBMUXD_PROXY` | 空 | Chromium 走的代理 |
| `WEBMUXD_TAB_MAX` | `10` | 同时最多几个 tab,超了挤掉最不活跃的 |
| `WEBMUXD_LOG_LIMIT` | `5000` | 日志满多少条切一刀(像 tmux 的 `history-limit`) |
| `WEBMUXD_HUMAN_YIELD` | `3000` | 人在 VNC 里动过之后,API 让路多少毫秒 |
| `WEBMUXD_VIEW_TOKEN` | 空 | 只读 token:能看画面、能读 `GET`,写操作一律 `403` |

## 3. 镜像

```dockerfile
ARG KASM_TAG=1.18.0                 # 锁 tag,别用 latest
FROM kasmweb/chromium:${KASM_TAG}   # Chromium,不是 Chromium —— 见下

USER root
COPY dist/sessiond    /opt/webmuxd/sessiond
COPY startup.sh     /dockerstartup/custom_startup.sh
RUN /opt/webmuxd/sessiond/bin/pip install -r /opt/webmuxd/sessiond/requirements.txt \
 && mkdir -p /data/shots && chown -R 1000:1000 /data /opt/webmuxd \
 && chmod +x /dockerstartup/custom_startup.sh

USER 1000
EXPOSE 7900
HEALTHCHECK --interval=10s --start-period=25s CMD curl -fsS localhost:7900/healthz || exit 1
```

**要给 Chromium 加调试端口,根本不用改镜像。** kasm 的 `custom_startup.sh` 里有
`ARGS=${APP_ARGS:-$DEFAULT_ARGS}`,环境变量直接注入(实测于 `kasmweb/chromium:1.18.0`):

```bash
docker run -e APP_ARGS="--remote-debugging-port=9222 \
                        --remote-debugging-address=127.0.0.1 \
                        --disable-infobars --disable-session-crashed-bubble" ...
```

> **基座实测(2026-08-08,`kasmweb/chromium:1.18.0`)**
> - `/dockerstartup/custom_startup.sh` 存在,权限 777
> - `APP_ARGS` 环境变量可注入 Chromium 参数,**不用重建镜像**
> - `custom_startup.sh` 有 `while true` 循环,Chromium 挂了会自动重拉
> - `/dockerstartup/maximize_window.sh` **每 ~10 秒把窗口重新最大化**——
>   任何在 X 层面挪窗口的做法都会被它撤销(见 [04 §5](04-chrome-ui-externalization.md))
> - WM 是 xfwm4,默认分辨率 1024×768,Chromium 139
> - **CDP 的 Host 头校验挡掉了容器外访问**,只能容器内连——印证了 sessiond 必须跑在容器里
> - 有 `wmctrl`/`xprop`/`xwininfo`/`xwd`,**没有 `xdotool`**
>
> 换 tag 时复核这一段即可。

**为什么是 Chromium 不是 Chromium。** Google Chrome 是专有软件,再分发受限;
我们要发一个镜像出去,捆 Chromium 就是许可问题。Chromium 是 BSD,随便发。

代价是**专有编解码器**(H.264 / AAC)不在里面,所以有些站点的视频放不了。
对"驱动网页"这个用途几乎无所谓,但**如果你的目标站点靠视频**,这条要先知道。

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
├── server.py     HTTP + WS(全部 API)
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
| Chromium profile(cookie / 登录态) | `/data/profile` | ✅ |
| 日志(动作 + tab 生死 + session 事件) | `/data/log.jsonl` `/data/log.1.jsonl` | ✅ |
| 截图 | `/data/shots/`(按 seq 命名) | ✅ |
| 下载文件 | `/data/downloads/` | ✅ |

**一个文件,不分 tab 也不分类型** —— 一行一条 JSON,要哪部分 grep 哪部分。
布局和保留策略见 [03 §3.1](03-log.md#11-一个文件)。

不挂卷 = 容器删了全没,跟 `tmux kill-server` 一样。想留就挂 `-v`。

日志满 `WEBMUXD_LOG_LIMIT` 条就切一刀,只留上一刀,连同那批截图一起删 ——
在线永远在 5000~10000 条之间,磁盘约 1GB 封顶([03 §7](03-log.md#5-保留))。
就是 tmux 的 `history-limit`,不是归档。

## 6. 崩了怎么办

| 情况 | 行为 |
| --- | --- |
| Chromium 崩溃 | sessiond 检测到 CDP 断开,**自动重启 Chromium**(profile 还在,页面丢失),日志记一条 `chrome_restarted` |
| sessiond 崩溃 | supervisor 拉起,Chromium 不受影响,**画面照看**(KasmVNC 是独立进程,不经它) |
| 容器 OOM | 容器退出;挂了卷的话 profile 和日志还在,`docker start` 回来 |

没有"unhealthy 状态机",没有 draining。崩了就重启,该丢的丢,像 tmux 里某个 pane 的进程死了一样。
