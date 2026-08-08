# webmux

浏览器版的 tmux。

一个基于 `kasm/chrome` 的容器:在浏览器里打开一个网址就能看到并直接操作里面那个远端 Chrome,
同时用 API 或 Python lib 从外面驱动同一个 Chrome。关掉网页,浏览器照常在跑。

- tab 条和地址栏被裁掉,由调用方在外面用 API 自己画
- 给智能体用的观测层:标注截图 + 元素表,直接喂多模态模型
- 操作日志就是 tmux 的 scrollback —— 它每一步看到什么、做了什么、页面变成什么样

设计文档:[`docs/v1/works`](docs/v1/works/) · 接口规格:[`docs/v1/api`](docs/v1/api/)
