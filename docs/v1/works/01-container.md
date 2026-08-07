# 01 · 容器

## 1. 一张图

```
┌─ 容器 (browserapi/operator) ────────────────────────────────┐
│                                                             │
│   :7900  nginx ──┬─ /        查看页面(画面 + 操作日志)    │
│                  ├─ /vnc/    → KasmVNC  :6901               │
│                  └─ /api/    → agentd   :7070               │
│                                                             │
│   agentd ──CDP──► Chrome (headful, 127.0.0.1:9222)          │
│      │                │                                     │
│      │                └─ X11 ─► KasmVNC ─► 人的鼠标键盘     │
│      └─ 操作日志 → /data/log.jsonl + /data/shots/           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**只暴露一个端口 7900。** 人看的页面和 API 在同一个 origin 下,省掉跨域、省掉两套鉴权、
`docker run -p 7900:7900` 一句话就完事。

| 内部端口 | 用途 | 是否出容器 |
| --- | --- | --- |
| 7900 | nginx,唯一入口 | ✅ |
| 6901 | KasmVNC | ❌ 只经 nginx |
| 7070 | agentd | ❌ 只经 nginx |
| 9222 | Chrome CDP | ❌ 锁 `127.0.0.1`,永不出容器 |

## 2. 起容器

```bash
docker run -d --name work \
  -p 7900:7900 \
  --shm-size=1g \                       # 少于 1G Chrome 会崩
  -e BAPI_TOKEN=changeme \              # 不设则不鉴权(仅限本机玩)
  -e BAPI_VIEWPORT=1280x800 \
  -v bapi-work:/data \                  # 想保住登录态就挂卷
  browserapi/operator:1.0
```

| 环境变量 | 默认 | 说明 |
| --- | --- | --- |
| `BAPI_TOKEN` | 空 | 设了则页面和 API 都要这个 token |
| `BAPI_VIEWPORT` | `1280x800` | 屏幕分辨率 = 视口 |
| `BAPI_START_URL` | `about:blank` | 启动打开的页面 |
| `BAPI_PROXY` | 空 | Chrome 走的代理 |
| `BAPI_LOG_LIMIT` | `500` | 操作日志保留多少条(像 tmux 的 `history-limit`) |

## 3. 镜像

```dockerfile
ARG KASM_CHROME_TAG=1.16.0          # 锁 tag,别用 latest
FROM kasmweb/chrome:${KASM_CHROME_TAG}

USER root
COPY dist/agentd    /opt/browserapi/agentd
COPY web/           /opt/browserapi/web/        # 查看页面(纯静态)
COPY nginx.conf     /etc/nginx/conf.d/bapi.conf
COPY startup.sh     /dockerstartup/custom_startup.sh
RUN /opt/browserapi/agentd/bin/pip install -r /opt/browserapi/agentd/requirements.txt \
 && mkdir -p /data/shots && chown -R 1000:1000 /data /opt/browserapi \
 && chmod +x /dockerstartup/custom_startup.sh

USER 1000
EXPOSE 7900
HEALTHCHECK --interval=10s --start-period=25s CMD curl -fsS localhost:7070/healthz || exit 1
```

**唯一需要对 kasm 基座动的手脚**,是接管 Chrome 的启动方式,让它带上调试端口:

```bash
# startup.sh
exec /opt/google/chrome/chrome \
  --remote-debugging-port=9222 \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir=/data/profile \
  --window-position=0,0 --window-size=${W},${H} \
  --no-first-run --no-default-browser-check \
  --password-store=basic \
  --disable-session-crashed-bubble --disable-infobars \
  "${BAPI_START_URL:-about:blank}"
```

> `kasmweb/chrome` 的启动钩子路径(`/dockerstartup/custom_startup.sh`)与用户 uid(1000)
> 在版本间变过。**锁定 tag 后实测确认**;不成立就直接覆盖 `ENTRYPOINT` 自己拉 Xvnc + Chrome。
> 这是唯一一处对基座的假设,出问题只需要改这一节。

**不加 `--headless`**(要 GUI 才能被看见),**不加 `--no-sandbox`**(保留 Chrome 沙箱),
**不用 CDP 的 `setDeviceMetricsOverride`** —— 那会让截图和人看到的画面对不上,
而"人和脚本看同一个画面"是这东西的全部意义。视口就是屏幕分辨率。

## 4. agentd

容器里唯一自己写的进程,几百行的量级:

```
agentd/
├── server.py     HTTP + WS(全部 API)
├── browser.py    CDP 连接、动作执行
├── observe.py    AX 树 → 元素表 → 标注截图
└── log.py        操作日志(append + 环形截断)
```

底层用 **Playwright 的 `connect_over_cdp()`**,不裸写 CDP —— 等待可见/可点击、iframe、
文件上传这些脏活它已经做对了。但 API 只暴露 browserapi 自己的动作名,
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

日志和截图按 `BAPI_LOG_LIMIT` 环形截断,老的自动删,不会把磁盘撑爆 —— 就是 tmux 的 `history-limit`。

## 6. 崩了怎么办

| 情况 | 行为 |
| --- | --- |
| Chrome 崩溃 | agentd 检测到 CDP 断开,**自动重启 Chrome**(profile 还在,页面丢失),日志记一条 `chrome_restarted` |
| agentd 崩溃 | supervisor 拉起,Chrome 不受影响 |
| 容器 OOM | 容器退出;挂了卷的话 profile 和日志还在,`docker start` 回来 |

没有"unhealthy 状态机",没有 draining。崩了就重启,该丢的丢,像 tmux 里某个 pane 的进程死了一样。
