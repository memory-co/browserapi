# webmuxd

**webmuxd ≈ tmux + ttyd,只是 pane 里渲染的不是 tty 字符,是浏览器像素。**

| 来自 | 能力 |
| --- | --- |
| **tmux** | 多路复用 + 持久化 + attach/detach |
| **ttyd** | 把它暴露成一个网页,能看、能操作、能分享链接 |
| **自己加的** | 程序化操作 + 给智能体的观测层与操作日志 |

终端世界里这两件事是分开的(`ttyd tmux new -A -s work`)。webmuxd 合成一个,
因为浏览器的渲染层本来就是网页——**暴露不是可选项,是本体**。

一个基于 `kasm/chrome` 的 session。起来之后:

- **在浏览器里打开一个网址,就能看到并直接操作里面那个远端 Chromium**
- **同时用 Python lib(或 HTTP API)从外面驱动同一个 Chromium**
- 关掉网页,浏览器照常在跑;下次打开还是那个状态
- **不带界面** —— 画面和 API 两个干净的口,怎么摆是上层的事

就这些。

## tmux 对照

| tmux / ttyd | webmuxd |
| --- | --- |
| `ttyd tmux new -A -s work` | **就是 webmuxd 本身** |
| `tmux new -s work` | `docker run -d --name work -p 6901:6901 -p 7900:7900 webmuxd` |
| `tmux attach -t work` | 浏览器打开 `http://localhost:6901` |
| detach(`Ctrl-b d`) | 关掉网页,容器继续跑 |
| `tmux send-keys` | `tab.click("登录")`(或 `POST /api/act`) |
| `tmux capture-pane` | `tab.observe()`(或 `GET /api/observe`) |
| scrollback 回滚历史 | 页面右侧的**操作日志** |
| 多个 client 同时 attach | 人和 API 同时操作,互不阻塞 |
| `tmux kill-session` | `docker rm -f work` |
| tmux server 持有会话状态 | server 持有 session,session 持有 profile / cookie / tab |
| ttyd 默认只读,`-W` 才可写 | 分享链接默认只读,要操作得显式要完整 token |

核心是 tmux 那个最有用的性质:**会话比观看者活得久,而且看的人和写脚本的人共用同一个会话。**

## 60 秒上手

```bash
webmuxd new -s work -p 7900 --vnc-port 6901        # 跑的是 kasmweb/chromium 原厂镜像
open http://localhost:6901        # 画面:看到 Chromium,可以直接用鼠标点
```

```python
from webmuxd import Webmuxd
web  = Webmuxd()
sess = web.session(id="work", port=7900, vnc_port=6901)
tab  = sess.open("https://example.com")
tab.click("登录")                  # 语义定位,不用写 CSS 选择器
tab.type("手机号", "13800000000")
print(tab.text())
```

一边跑脚本,一边在 `http://localhost:6901` 里实时看着它点。卡住了就自己上手点两下,脚本继续跑。

## 文档

| 文件 | 内容 |
| --- | --- |
| [01-container.md](01-container.md) | 容器怎么改、怎么起、状态存哪 |
| [02-lib-and-api.md](02-lib-and-api.md) | **Python lib 是主体**,HTTP API 是它的导出面 |
| [03-log.md](03-log.md) | 操作日志(scrollback):存哪、三类记录、保留 |
| [04-chrome-ui-externalization.md](04-chrome-ui-externalization.md) | 去掉 Chromium 的 tab 条和地址栏,改由外面用 API 自己画 |
| [05-server-session-runtime.md](05-server-session-runtime.md) | server / session / runtime 三层概念,与 tmux 的完整对照 |
| [06-tab-sync.md](06-tab-sync.md) | **tab 的一进一出** —— `open()` 怎么落到 Chromium,人点出来的新 tab 怎么被感知 |
| [07-popup-windows.md](07-popup-windows.md) | `window.open` 的 popup 是窗口不是 tab —— 能不能转化掉,以及别人怎么做的 |

规格在上一级([`..`](../)):[`api`](../api/) HTTP · [`cli`](../cli/) 命令行 · [`sdk`](../sdk/) Python。
本目录是**为什么**,那三个目录是**做成什么样**。

## 明确不做

保持它是个工具,不是平台:

- ❌ 控制面 / 会话编排 / 容器池 —— 你要多个就 `docker run` 多次
- ❌ 数据库 / 对象存储 —— 日志和截图就在容器里,像 tmux 的 scrollback
- ❌ 多租户 / RBAC / 配额 —— 一个容器一个用户,权限交给网络层
- ❌ 内置 LLM —— 它是手和眼,大脑你自己接
- ❌ k8s operator / webhook / OTel —— 需要了外面自己包

> 判断新功能该不该加,问一句:**tmux 会做这个吗?** 不会就别加。
