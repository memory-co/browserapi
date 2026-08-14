# webmuxd

**webmuxd ≈ tmux + ttyd,只是 pane 里渲染的不是 tty 字符,是浏览器像素。**

一个基于 `kasm/chrome` 的容器:在浏览器里打开一个网址就能看到并直接操作里面那个远端 Chrome,
同时用 Python lib 从外面驱动同一个 Chrome。关掉网页,浏览器照常在跑。

- tab 条和地址栏被裁掉,由调用方在外面用 API 自己画
- 给智能体用的观测层:标注截图 + 元素表,直接喂多模态模型
- 操作日志就是 tmux 的 scrollback —— 它每一步看到什么、做了什么、页面变成什么样

```bash
pip install webmuxd && webmuxd install
webmuxd new -s demo -p 7900 --vnc-port 6901 --runtime container
```

**先跑一遍:[QUICKSTART.md](QUICKSTART.md)** —— 浏览器打开 VNC 那个口看着,
同时用命令行点一下,页面会在你眼前跳过去。

**webmuxd 是一个 `*muxd` 组件** —— 一扇 HTTP 上的窗给人,一个 Python 把手给程序。
这一族的规范定在 [shellbase](https://github.com/memory-co/shellbase):
[new-interface](https://github.com/memory-co/shellbase/blob/main/docs/v1/new-interface.md)(为什么是这个形状) · [muxd-spec](https://github.com/memory-co/shellbase/blob/main/docs/v1/muxd-spec.md)(算不算一个组件)

代码同时放在 [GitHub](https://github.com/memory-co/webmuxd) 和
[CNB](https://cnb.cool/agentuse/webmuxd)(国内访问),两边是同一份。

设计文档:[`docs/v1/works`](docs/v1/works/) —— 为什么这么做
规格([`docs/v1`](docs/v1/)):[`sdk`](docs/v1/sdk/) Python(主体) · [`api`](docs/v1/api/) HTTP 导出面 · [`cli`](docs/v1/cli/) 命令行
