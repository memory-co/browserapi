# webmuxd v2 · 规格

**一句话:画面自己产。**

v1 的画面来自别人的 VNC 镜像,webmuxd 只把那个端口的 URL 报出来,不解析里面一个字节
([v1/works/08 §2](../v1/works/08-browser-runtime.md#2-判据哪一半在契约里))。
v2 用 CDP 的 `Page.startScreencast` 自己产帧、自己收输入 —— VNC、桌面、特制镜像整条路砍掉。

```
v1:  一个画面端口(别人的) + 一个 CDP 端点(别人的)  →  webmuxd 只报 URL
v2:  一个 CDP 端点进  →  webmuxd 自己吐一个 HTTP 口出(画面和 API 同一个口)
```

```python
web  = Webmuxd()
sess = web.session(id="work", port=7900)      # 只剩一个端口
tab  = sess.open("https://example.com")
print(sess.view_url)                          # http://127.0.0.1:7900/ —— 和 API 同一个
```

## v1 去哪了

[`v1/`](../v1/) 不动。它是已经发出去的形状,不是错的 —— 在没有自产画面这条路之前,
租一个 VNC 镜像是当时能做的最好选择,而且那些实测记录(Chromium 的 CDP 只绑
loopback、KasmVNC 的抽象 socket、kasm 的窗口看门狗)全部仍然成立,只是**不再咬我们了**。

相对 v1,**定位、观测、日志、tab 表、错误模型一个字没动**,变的全在画面这一半。

## 目录

设计稿在 [`works`](works/) —— 讲**为什么**。规格三个目录讲**做成什么样**,
和 v1 一样是 sdk → api → cli 的顺序([v1/works/02](../v1/works/02-lib-and-api.md))。

| 目录 | 是什么 | 状态 |
| --- | --- | --- |
| [`works`](works/) | 设计稿与实测记录 | **本轮先写这个** |
| `sdk` | Python 包 —— 主体,行为定义在这儿 | 待写,`view/` 一节是新的,其余从 v1 平移 |
| `api` | HTTP + WS 的线上格式 | 待写,新增 `WS /api/view` |
| `cli` | `webmuxd` 命令 | 待写,`--view-port` 退役 |

## 与上一层的关系

`*muxd` 那一族的规范定在 [shellbase](https://github.com/memory-co/shellbase):
[new-interface](https://github.com/memory-co/shellbase/blob/main/docs/v1/new-interface.md) ·
[muxd-spec](https://github.com/memory-co/shellbase/blob/main/docs/v1/muxd-spec.md)。

v2 让 webmuxd **更符合**那个形状,不是更偏离:规范要的是"HTTP 上的一扇窗 + 一个能控它的把手",
v1 交出去的是两扇窗(一扇还是租的),v2 就是一扇。
