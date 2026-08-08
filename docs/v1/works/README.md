# webmux —— 浏览器版的 tmux

一个基于 `kasm/chrome` 的容器。起来之后:

- **在浏览器里打开一个网址,就能看到并直接操作里面那个远端 Chrome**
- **同时用 API 或 Python lib 从外面驱动同一个 Chrome**
- 关掉网页,浏览器照常在跑;下次打开还是那个状态

就这些。

## tmux 对照

| tmux | webmux |
| --- | --- |
| `tmux new -s work` | `docker run -d --name work -p 7900:7900 webmux` |
| `tmux attach -t work` | 浏览器打开 `http://localhost:7900` |
| detach(`Ctrl-b d`) | 关掉网页,容器继续跑 |
| `tmux send-keys` | `POST /api/act` 或 `b.click("登录")` |
| `tmux capture-pane` | `GET /api/observe` |
| scrollback 回滚历史 | 页面右侧的**操作日志** |
| 多个 client 同时 attach | 人和 API 同时操作,互不阻塞 |
| `tmux kill-session` | `docker rm -f work` |
| tmux server 持有会话状态 | 容器持有 profile / cookie / 标签页 |

核心是 tmux 那个最有用的性质:**会话比观看者活得久,而且看的人和写脚本的人共用同一个会话。**

## 60 秒上手

```bash
docker run -d --name work -p 7900:7900 webmux/operator:1.0
open http://localhost:7900        # 看到 Chrome,可以直接用鼠标点
```

```python
from webmux import Browser
b = Browser("http://localhost:7900")

b.goto("https://example.com")
b.click("登录")                    # 语义定位,不用写 CSS 选择器
b.type("手机号", "13800000000")
print(b.text())
```

一边跑脚本,一边在 `http://localhost:7900` 里实时看着它点。卡住了就自己上手点两下,脚本继续跑。

## 文档

| 文件 | 内容 |
| --- | --- |
| [01-container.md](01-container.md) | 容器怎么改、怎么起、状态存哪 |
| [02-api-and-lib.md](02-api-and-lib.md) | HTTP API 与 Python lib(同一套东西的两个壳) |
| [03-view-and-log.md](03-view-and-log.md) | 查看页面 + 操作日志(scrollback) |
| [04-chrome-ui-externalization.md](04-chrome-ui-externalization.md) | 去掉 Chrome 的 tab 条和地址栏,改由外面用 API 自己画 |

接口规格在 [`../api`](../api/)。

## 明确不做

保持它是个工具,不是平台:

- ❌ 控制面 / 会话编排 / 容器池 —— 你要多个就 `docker run` 多次
- ❌ 数据库 / 对象存储 —— 日志和截图就在容器里,像 tmux 的 scrollback
- ❌ 多租户 / RBAC / 配额 —— 一个容器一个用户,权限交给网络层
- ❌ 内置 LLM —— 它是手和眼,大脑你自己接
- ❌ k8s operator / webhook / OTel —— 需要了外面自己包

> 判断新功能该不该加,问一句:**tmux 会做这个吗?** 不会就别加。
