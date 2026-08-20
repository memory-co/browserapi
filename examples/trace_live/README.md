# CDP 流控制 + Playwright trace 实时展示

```bash
python3 examples/trace_live/serve.py --port 8090
# 打开 http://<这台机器>:8090/
```

一个口子,上下两半:

| | |
| --- | --- |
| **上半屏** | 能操作的画面 —— `Page.startScreencast` 出的帧,鼠标/滚轮/键盘经 `Input.*` 送回同一个 tab |
| **下半屏** | **Playwright Trace Viewer**,你每做完一个动作它就多一条 |

先点一下画面(拿到焦点)再敲键盘。地址栏能换页面。

## 为什么这事能成

**Playwright 录不到你的操作。** 它的 DOM 快照只在自己的 API 调用前后拉
([c §13.2](../../docs/v2/works/c-pixels.md#132-playwright-trace根本不是一条来源)),
而这里的输入是裸 `Input.dispatchMouseEvent` —— 不构成 Playwright 调用。
让它来录,trace 里会一条动作都没有。

**所以 trace 不是它录的,是我们写的**,格式照它的来
([c §13.4](../../docs/v2/works/c-pixels.md#134-换个用途同一项技术就成立了))。
动作边界本来就是我们定义的,在那个位置拉一次 DOM 序列化就行:

| 你做的 | 变成 |
| --- | --- |
| 按下鼠标 | 一条 `click`,标题用命中元素的可见文字,`input.point` 就是那个点 |
| 敲一串字(停 0.9s 收口) | 一条 `type`,**不是一个字一条** —— 否则时间轴全是噪声 |
| 导航 | 一条 `nav` |

每条动作都拍**前后两张 DOM 快照**,并把当前那帧截屏塞进 filmstrip。
标题前缀是「谁做的」(`[人] click …`)—— trace 没有这个字段,只能放标题里,
而这正是我们比它多出来的那样东西([i §3](../../docs/v2/works/i-agent-surface.md#3-一条行为流每条标明是谁做的))。

## 实时是怎么做到的

不是 reload。trace viewer 自己听 `postMessage`:

```js
viewer.contentWindow.postMessage({ method: "load", params: { trace: blob } }, "*")
```

每落一条动作,服务端重拼一个 trace.zip,页面 `fetch` 下来再 post 进去,
**viewer 原地换内容**,不重新加载。

## viewer 从哪来

默认用托管的 **https://trace.playwright.dev/**(纯前端,trace 不上传)。

要离线的话指到本地那份静态包:

```bash
--viewer-dir node_modules/playwright-core/lib/vite/traceViewer
```

> **但本地那份必须从 `127.0.0.1` 打开**(端口转发)。它靠 service worker 渲染 DOM 快照,
> 而 service worker 只在安全上下文里注册 —— 从内网 IP 访问时**快照面板会静默空白**。
> 默认选托管那份就是因为这个:它是 https,你怎么访问都不会掉进这个坑。

## 实测(2026-08-20)

用鼠标点了输入框、打了 `13800000000`、又点了一下,trace 里就是这四条:

```
[人] nav   http://127.0.0.1:8090/demo   453ms
[人] click phone                         457ms
[人] type  13800000000                   2.4s
[人] click ③ 表单(点它、填它)            457ms
```

画面 57.7 fps,控制台零报错。

## 已知的粗糙处

- **每条动作重拼整个 trace.zip 再整份 post 过去。** 动作多了会变慢 ——
  真做应该只追加。这里图的是先看见东西
- viewer 换 trace 之后**选中项会回到默认**,不会自动停在最新那条
- 只跟一个 tab;新开的 tab 不进 trace
- `resourceOverrides` 没接:外站的 CSS / 图片在快照回放里会去打原站
- 动作边界是拍脑袋的三条(按下 / 打字停顿 / 导航),
  真正该怎么切见 [i §3.2](../../docs/v2/works/i-agent-surface.md#32-什么算一条行为)
- chrome 是这个服务的子进程,`Ctrl-C` 和 `kill` 都会把它关干净
