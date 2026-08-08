# 01 · 容器

## 1. 一张图

```
┌─ session 容器 (webmuxd/kasm-chromium) ───────────────────────┐
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

这是 `runtime="container"` 实际拼出来的命令:

```bash
docker run -d --name webmuxd-work \
  --label webmuxd.session=work \
  --shm-size=1g \                              # 少于 1G Chromium 会崩
  -p 127.0.0.1:6901:6901 \                     # KasmVNC —— 给人
  -p 127.0.0.1:7900:7900 \                     # webmuxd API —— 给代码
  -e VNC_PW=<token> \
  -e LAUNCH_URL=https://example.com \
  -e APP_ARGS="--remote-debugging-port=9222 --start-maximized --window-size=1280,800" \
  -v webmuxd-work:/data \                      # 想保住登录态就挂卷
  webmuxd/kasm-chromium:0.1.0
```

**前三个环境变量是 kasm 自己的,不是我们发明的** —— 用它现成的,
就不用碰它的启动脚本([§3](#3-镜像))。

| 环境变量 | 谁的 | 说明 |
| --- | --- | --- |
| `VNC_PW` | kasm | KasmVNC 的密码,用户名固定 `kasm_user`。这就是"拿着 token 的人能用" |
| `LAUNCH_URL` | kasm | 启动打开的页面 |
| `APP_ARGS` | kasm | 直接拼到 Chromium 命令行 —— 调试端口从这儿进去 |
| `WEBMUXD_TAB_MAX` | 我们 | 同时最多几个 tab,超了挤掉最不活跃的 |
| `WEBMUXD_LOG_LIMIT` | 我们 | 日志满多少条切一刀(像 tmux 的 `history-limit`) |
| `WEBMUXD_HUMAN_YIELD` | 我们 | 人在 VNC 里动过之后,API 让路多少毫秒 |

**端口只绑 `127.0.0.1`。** 要放出去是上层的决定,不该是我们的默认 ——
这东西一旦对公网开着,拿到 VNC 密码就等于拿到一个已登录的浏览器。

## 3. 镜像

**只有两条 RUN。** 底座已经是个能用的桌面了,我们不重复造:

```dockerfile
FROM kasmweb/chromium:1.18.0        # 锁 tag,别用 latest
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-pip \
 && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir "webmuxd==0.1.0"
USER 1000
```

`webmuxd install` 在本机 build 它,**不推 registry** —— 两条 RUN 不值得
为它维护一个仓库,而版本钉死意味着谁 build 出来都是同一个。

**没有 `COPY startup.sh`,也没有 `HEALTHCHECK`。** 镜像里不启动 sessiond ——
容器起来之后由 runtime `docker exec` 进去起([§4](#4-sessiond))。
镜像因此是"死"的:只有一个装好的包,没有我们的启动逻辑,
出问题的时候你查的是 `docker exec` 那条命令,不是镜像层。

**要给 Chromium 加调试端口,根本不用改镜像。** kasm 的 `custom_startup.sh` 里有
`ARGS=${APP_ARGS:-$DEFAULT_ARGS}`,环境变量直接注入。

> **基座实测(2026-08-08,`kasmweb/chromium:1.18.0`)**
> - `/dockerstartup/custom_startup.sh` 存在,权限 777
> - 注入参数的变量叫 **`APP_ARGS`**,不是 `CHROME_ARGS` —— 后者写了没用,
>   会被静默忽略,容易以为生效了
> - `LAUNCH_URL` 是启动页,`VNC_PW` 是 KasmVNC 密码(用户名 `kasm_user`)
> - **`--remote-debugging-address` 已经不起作用**:给了 `0.0.0.0` 也照样只绑
>   容器内 `127.0.0.1:9222`(实测 `/proc/net/tcp` 为 `0100007F:2406`)。
>   这反而是我们要的 —— 调试口天然出不去
> - `/dockerstartup/kasm_post_run_*.sh` 这几个 hook **在独立镜像里根本不触发**
>   (只有 Kasm Workspaces 平台会调),所以别指望用它自启 sessiond
> - **镜像里没有 pip**(有 python3.10,但 `ensurepip` 也没有),要 `apt install python3-pip`
> - `custom_startup.sh` 有 `while true` 循环,Chromium 挂了会自动重拉
> - `/dockerstartup/maximize_window.sh` **每 ~10 秒把窗口重新最大化**——
>   任何在 X 层面挪窗口的做法都会被它撤销(见 [04 §5](04-chrome-ui-externalization.md))
> - WM 是 xfwm4,默认分辨率 1024×768,Chromium 139
> - **CDP 的 Host 头校验挡掉了容器外访问**,只能容器内连——印证了 sessiond 必须跑在容器里
> - 有 `wmctrl`/`xprop`/`xwininfo`/`xwd`,**没有 `xdotool`**
>
> 换 tag 时复核这一段即可。

**为什么是 Chromium 不是 Chrome。** Google Chrome 是专有软件,再分发受限;
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

容器里唯一自己写的进程:

```
webmuxd/serve/     app.py(路由) session.py(编排) __main__.py(入口)
webmuxd/core/      cdp.py tabs.py locate.py act.py observe.py log.py shim.py
```

**它跑在容器里,不在你机器上。** 起法是容器起来之后 exec 进去:

```bash
docker exec -d -u root <cid> bash -c \
  'exec python3 -m webmuxd.serve --cdp http://127.0.0.1:9222 --port 7900 --data /data'
```

这样 sessiond 和 Chromium 在同一个 network namespace,**CDP 一步都不用出容器**。
外面能碰到的只有 6901 和 7900 —— 这不是加固措施,是拓扑本身决定的。

**不用 Playwright,直接 CDP。** 早先这里写的是 `connect_over_cdp()`。
但我们要的东西它恰好不给或要绕:`Target.setDiscoverTargets` 的原始事件、
`targetInfo.openerId`、自己决定 attach 时机 —— 而且它会建自己的 tab 模型,
和我们的 tab 表打架([works/06](06-tab-sync.md))。它擅长的自动等待,
我们本来就要自己定义。

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
