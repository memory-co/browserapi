# CDP 流控制 + 下半屏实时重放

```bash
python3 examples/live_replay/serve.py --port 8090                 # 默认 rrweb
python3 examples/live_replay/serve.py --port 8090 --replay trace  # 换成 Playwright Trace
# 打开 http://<这台机器>:8090/
```

上半屏是**能操作的画面**(`Page.startScreencast` 出的帧,鼠标/滚轮/键盘经 `Input.*`
送回同一个 tab)。先点一下画面拿焦点再敲键盘。下半屏是重放。

## 两种重放器,差别是结构性的

| `--replay` | 下半屏 | 节奏 | 为什么 |
| --- | --- | --- | --- |
| **`rrweb`**(默认) | `Replayer` 跑 live 模式 | **连续流** —— 页面动它就动 | 它本来就是流,`addEvent()` 一条一条喂 |
| `trace` | Playwright Trace Viewer | **一条动作一跳** | trace 是**产物格式**,时间轴是动作轴;每落一条动作要重拼整包再 post 进去 |

`trace` 那条不顺不是没调好,是拿事后复盘的东西当实时用
([c §13.2](../../docs/v2/works/c-pixels.md#132-playwright-trace根本不是一条来源))。
留着是为了能直接对比。

**两种都不改变一件事:输入永远走 CDP。** 下半屏只是看,不承载操作
([b §1](../../docs/v2/works/b-input.md#1-收口在哪))。

## 实测(靶页,1024×768,2026-08-20)

| | rrweb | CDP 截屏 |
| --- | --- | --- |
| 带宽 | **114 KB/s 事件 + 1369 KB 资源** | 2686 KB/s(未限流的 60fps canvas) |
| canvas | **重放得出来**(开了 `recordCanvas`) | 有 |
| 表单里打的字 | 跟过去了 | 有 |
| 延迟 | **落后约 1.5 秒**(两边时钟一比就看出来) | 实时 |

> **省下来的一直都是没画出来的那部分。** 同一套 DOM 流,
> [dom_stream](../dom_stream/) 那个例子里只要 17.9 KB/s —— 因为它既没传 canvas
> 也没传资源。这里开了 `recordCanvas` 是 114 KB/s,再加上资源代理那 1.3 MB。
> **每让它多画出一样东西,账就往截屏那边靠一截。**

`trace` 模式下动作边界取三样:按下鼠标、敲完一串字(停 0.9s 收口)、导航;
每条拍前后两张 DOM 快照 + 一帧截屏,标题带「谁做的」。
Playwright 自己录不到这些 —— 输入是裸 CDP,不构成它的 API 调用,
所以 trace 是我们写的,格式照它的来
([c §13.4](../../docs/v2/works/c-pixels.md#134-换个用途同一项技术就成立了))。

## 图片和视频:能补到哪一步

rrweb 默认只记 `src`,**重放端自己回原地址拉**。这在本机看着没问题,
换成要登录的站、或者观看端在别的网里,就是一片破图。三种补法量下来:

| | 默认 | `--inline-images` | **资源代理**(默认开) |
| --- | --- | --- | --- |
| 本站图 | 回原站拉 | data URL ✓ | **走 `/res` ✓** |
| **跨域图** | 回原站拉 | **✗ 内联不了** | **走 `/res` ✓** |
| **普通 mp4** | 回原站拉 | 不处理 | **走 `/res` ✓,960×540 解得出来** |
| **`srcObject` / MSE 视频** | ✗ | ✗ | **✗** |
| 全量快照 | 17 KB | **91 KB(5.4×)** | 17 KB(资源另走 HTTP,可缓存、可去重) |

**跨域图内联不了是机制决定的**:`inlineImages` 要把图画进 canvas 再取字节,
跨域没 CORS 头就污染画布。而代理是从 CDP 收响应体
(`Network.getResponseBody`),**走的是浏览器已经拿到的字节,不受同源策略管** ——
实测那张 google 的 logo,内联失败、代理成功。

> **代理能补的是「地址够不够得着」,补不了「有没有帧」。**
> `srcObject` 那个视频的画面来自一条 `MediaStream`,**根本没有 URL**;
> 真实站点的 MSE/`blob:` 也一样。rrweb 记得了元素和播放位置,记不了帧 ——
> 实测重放里它是 `videoWidth 0`。

## 那条线在哪

每补一样缺的,就往「传像素」退一步:

```
canvas   → recordCanvas    其实已经是在传图
图片/mp4 → 资源代理        在传原始字节
MSE 视频 → 只能自己抓帧    ——那就是又写了一条截屏通道
```

**补到最后,这条来源会变成另外那条,只是绕了一圈、还更贵。**
所以该停在哪是个设计决定,不是能力问题:
[c §13.1](../../docs/v2/works/c-pixels.md#131-rrweb是一条来源但代价买不起)。

## 做的时候踩到的三个坑

**① 注入脚本会递归。** `addScriptToEvaluateOnNewDocument` 对**每一个新文档**生效,
包括 rrweb 自己造出来的 `about:blank` iframe —— 被注入的 iframe 又造 iframe,
实测**每秒新建二十来个**,主页面的全量快照直接被饿死(只收到 Meta,没有 FullSnapshot)。
必须加两条守卫:只在顶层、只在 `http(s)` 页面上录。

**② UMD 后面要跟分号。** rrweb 的 bundle 最后一行是 `}))`,
后面直接接 `(() => …)()` 会被解析成「调用上一个表达式的结果」,
报 `(intermediate value)(...) is not a function` —— 和 rrweb 一点关系没有。

**③ 五百多 KB 的 `Runtime.evaluate` 会挂住。** 所以记录器只走
`addScriptToEvaluateOnNewDocument`(不需要等回包)。
代价是**它对「已经打开着的那一页」不生效**,要等下一次导航。

## 已知的粗糙处

- rrweb 落后约 1.5 秒,没去调 —— live 模式按时间戳推进,基线取的是第一条事件
- **记录器有五百多 KB,整个注进被自动化的页面**。这是它的真实代价,
  比现在那个光标探针大得多([c §13.4④](../../docs/v2/works/c-pixels.md#134-换个用途同一项技术就成立了))
- 只跟一个 tab;新开的 tab 不进重放
- `trace` 模式每条动作重拼整个 zip 再整份 post 过去,动作多了会变慢
- rrweb 的 bundle 第一次跑会下到 `~/.cache/webmuxd-examples/`
- chrome 是这个服务的子进程,`Ctrl-C` 和 `kill` 都会关干净
