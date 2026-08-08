# 04 · tab bar 与 url bar 外化

**一句话**:VNC 画面里只剩页面内容,Chrome 自带的 tab 条和地址栏不可见;
tab 列表和 URL 状态走 API 出来,由调用方在外面自己画。
页面里点链接冒出新 tab,外面能立刻感知到。

## 1. 最终形态

```
┌─ 你自己写的网页 ────────────────────────────────────────────────┐
│ ┌──────────┬──────────┬──────────┐                    ← 你画的  │
│ │ ● 购物车 │ 订单确认 │ 帮助中心 │ ＋                    tab 条 │
│ ├──────────┴──────────┴──────────┴──────────────────┐          │
│ │ ← → ⟳  🔒 shop.example.com/cart                   │ ← 你画的 │
│ └───────────────────────────────────────────────────┘   地址栏 │
│ ┌───────────────────────────────────────────────────┐          │
│ │        VNC 画面 —— 只有页面内容                    │          │
│ └───────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
     ▲ 上面两条是普通 HTML,数据走 /api/tabs + WS
     ▲ 下面那块是 VNC
```

## 2. 怎么把 Chrome 的 UI 弄没

**在 iframe 上裁掉。** 画面本来就要被嵌进你的页面,那就让 iframe 往上偏移 `crop_top` 像素,
外面套一层 `overflow:hidden` 的壳。tab 条和地址栏被裁在可视区之外,壳里只剩页面内容。

```html
<div style="overflow:hidden; height:680px">      <!-- 680 = 768 - 88 -->
  <iframe src="https://host:6901/?..." 
          style="width:1024px; height:768px; margin-top:-88px; border:0"></iframe>
</div>
```

```
        ┌─────────────────────┐  ← iframe 顶部,被壳裁掉
        │ tab 条 / 地址栏     │     (88px)
壳顶 ─► ├─────────────────────┤
        │   页面内容           │  ← 你只看得到这块
        └─────────────────────┘
```

好处:

- **不碰 X、不碰窗口管理器、不碰 Chrome 启动参数**,没有任何被 clamp 或被看门狗推回去的风险(见 §5)
- **鼠标坐标不用自己算**——iframe 整体位移,浏览器的命中测试自动对上
- **tab 语义完全原生**:`target=_blank`、`window.open`、Ctrl+点击、tab 顺序,全是 Chrome 自己的行为,一行都不用模拟

### crop_top 从哪来

不要写死 88。sessiond 用 CDP 量,通过 API 报出来:

```js
window.outerHeight - window.innerHeight    // tab条 + 工具栏 的实际高度
```

```jsonc
// GET /api/viewport
{ "screen": {"w":1024, "h":768}, "crop_top": 88, "page": {"w":1024, "h":680} }
```

**它会在运行时变**,所以要发事件让外面重新裁:

```jsonc
{ "type":"viewport.changed", "crop_top": 0 }    // 视频全屏了,UI 高度归零
{ "type":"viewport.changed", "crop_top": 116 }  // 有人按了 Ctrl+Shift+B 开出书签栏
```

### 想要页面视口正好是某个尺寸

屏幕高 = 想要的页面高 + `crop_top`。但 `crop_top` 得等 Chrome 起来才量得到,所以是两段式:
容器按默认分辨率起 → sessiond 量出 `crop_top` → `xrandr` 把 X 分辨率调成 `page_h + crop_top`。
不介意差那几十像素的话,这步可以省。

## 3. 外面画 tab 条和地址栏需要什么 —— CDP 给不给

| 要画的 | CDP 来源 | 拿得到吗 |
| --- | --- | --- |
| tab 列表、顺序 | `Target.getTargets` | ✅ |
| 新 tab 出现 / 关闭 | `Target.targetCreated` / `targetDestroyed` | ✅ |
| URL / 标题变化 | `Target.targetInfoChanged`、`Page.frameNavigated` | ✅ |
| 切换 / 新建 / 关闭 tab | `Target.activateTarget` / `createTarget` / `closeTarget` | ✅ |
| 导航、刷新、停止 | `Page.navigate` / `reload` / `stopLoading` | ✅ |
| 前进后退是否可用 | `Page.getNavigationHistory`(entries + currentIndex) | ✅ |
| 前进后退跳转 | `Page.navigateToHistoryEntry` | ✅ |
| 转圈(在不在加载) | `Page.frameStartedLoading` / `frameStoppedLoading` | ✅ |
| https 小锁 | `Security.securityStateChanged` | ✅ |
| 当前激活的是哪个 tab | 没有现成事件 | ⚠️ 见 §4.1 |
| favicon | 没有现成事件 | ⚠️ sessiond 读 DOM 的 `link[rel~=icon]` 代抓并缓存 |
| 加载进度百分比 | 无 | ❌ 只能转圈,画不了精确进度条 |

**够用。** 缺的两样一个能绕,一个无关紧要。

## 4. API

形状对齐 `chrome.tabs` 扩展 API —— 写过 Chrome 扩展的人零学习成本。

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/tabs` |
| `POST` | `/api/tabs` 新建 `{url, active}` |
| `POST` | `/api/tabs/{id}/activate` 切过去(VNC 画面随之切) |
| `DELETE` | `/api/tabs/{id}` |
| `POST` | `/api/tabs/{id}/goto` `{url}` |
| `POST` | `/api/tabs/{id}/back` `/forward` `/reload` `/stop` |
| `POST` | `/api/tabs/reorder` `{order:[id,...]}` 拖拽排序 |
| `GET` | `/api/tabs/{id}/favicon` |

```jsonc
// GET /api/tabs
{ "tabs": [
  { "id":"t_3", "index":0, "active":true,
    "url":"https://shop.example.com/cart", "title":"购物车",
    "loading":false, "security":"secure",
    "can_go_back":true, "can_go_forward":false,
    "favicon":"/api/tabs/t_3/favicon", "opener":null },
  { "id":"t_7", "index":1, "active":false,
    "url":"https://shop.example.com/order/9182", "title":"订单确认",
    "loading":true, "security":"secure",
    "can_go_back":true, "can_go_forward":false,
    "opener":"t_3" }                       // ← 从 t_3 里点链接开出来的
] }
```

### 事件

```jsonc
// WS /api/events
{ "type":"tab.created",   "tab":{...}, "reason":"link_target_blank" }
{ "type":"tab.updated",   "id":"t_7", "changed":{ "title":"订单确认", "loading":false } }
{ "type":"tab.activated", "id":"t_7", "previous":"t_3" }
{ "type":"tab.closed",    "id":"t_7" }
```

`tab.updated` 只发变化的字段,外面做局部更新。

`reason` 说明这个 tab 怎么冒出来的:`api` / `link_target_blank` / `window_open` /
`ctrl_click` / `user_ctrl_t`(人在 VNC 里按了 Ctrl+T)。你的 tab 条可以据此决定要不要自动切过去。

`opener` 标出"从哪个 tab 开出来的",想画成子 tab 或加来源提示都行。

### Python lib

lib 自己就订着这条流,**内存里一直有一份完整的 tab 表** ——
所以画 tab 条不用监事件,直接读就行:

```python
for t in sess.tabs:               # 读内存,0 往返
    print(t.index, t.title, t.url, "●" if t.active else "")

tab = sess.open("https://example.com")
tab.activate(); tab.close()

ui.render(sess.tabs, sess.active)  # 值一直是新的
```

这套外挂 UI 的接口是先为 lib 设计的,HTTP 那份是它的导出面
([works/02](02-lib-and-api.md))。TypeScript 写的前端拿不到这份内存,
那才需要自己订 `tab.*` 做局部合并。

### 4.1 「当前是哪个 tab」不去观测,直接记账

CDP 没有"tab 被激活了"这种事件。但也不用为此发明观测手段 —— **反过来做**:
`active` 是 sessiond 自己的字段,它改完用 `Target.activateTarget` 把 Chrome 拽过来对齐。

能改它的只有 API 的 activate、新 tab 打开、当前 tab 被关 —— 三种 sessiond 都当场知道。
观看者一接进来(有 UI 连上那条 WS)再对齐一次。

**人点不到 Chrome 自己的 tab 条**——它被裁在可视区外,连命中测试都进不去,
点上去落在你画的那条 bar 上,也就是走 API。所以漂移只可能来自键盘快捷键,
下次进入时自愈。细节见 [api/tabs.md §5](../api/tabs.md#5-当前是哪个-tab是-sessiond-说了算)。

新 tab 怎么被感知到,见 [06](06-tab-sync.md)。

## 5. 基座实测记录

在 `kasmweb/chromium:1.18.0` 上实际跑过一遍(2026-08-08),记录如下。
这些取代了之前对 kasm 镜像的猜测:

| 事实 | 值 |
| --- | --- |
| 默认 X 分辨率 | 1024×768 |
| Chrome 版本 | 139 |
| 窗口管理器 | **xfwm4**(完整 xfce4 会话:xfdesktop / xfsettingsd / xfce4-notifyd) |
| 启动钩子 | `/dockerstartup/custom_startup.sh` **存在,权限 777** |
| **注入 Chrome 参数** | **`-e APP_ARGS="..."` 直接生效,不用改镜像** |
| Chrome 拉起方式 | `custom_startup.sh` 里 `while true` 循环,进程没了就重拉 |
| **窗口看门狗** | **`/dockerstartup/maximize_window.sh` 每 ~10 秒把窗口重新最大化一次** |
| 沙箱 | 镜像自带 `--no-sandbox`(kasm 的选择) |
| CDP | `APP_ARGS` 加 `--remote-debugging-port=9222` 即可用 |
| CDP 外部访问 | **被 Chrome 的 Host 头校验挡掉**,只能容器内访问 → 印证了 sessiond 必须在容器里 |
| 可用 X 工具 | `wmctrl` / `xprop` / `xwininfo` / `xwd` 有;**`xdotool` 没有** |

关于窗口偏移那条路(已放弃,存档):

- `wmctrl -e 0,0,-78,...` **能**把窗口挪到负 Y,xfwm4 不 clamp
- 但 Chrome 自己的 `--window-position=0,-88` 负值**不生效**(`--window-size` 生效)
- 而且 `maximize_window.sh` 会周期性把窗口推回最大化,**任何 X 层面的偏移都会被反复撤销**

最后一条是选 iframe 裁剪的直接理由:**页面层裁剪,看门狗管不着。**

## 6. 顺带会掉出来的东西(不影响架构,以后按需加)

tab 条和地址栏被裁掉之后,一批挂在工具栏上的原生 UI 会变成"看不见但仍然阻塞":
下载气泡、权限请求(定位/通知/摄像头)、文件选择框、HTTP Basic 认证框、`alert`/`confirm`。

这些**都是 CDP 能拦下来的**(`Browser.downloadWillBegin`、`Browser.setPermission`、
`Page.setInterceptFileChooserDialog`、`Fetch.authRequired`、`Page.javascriptDialogOpening`),
处理方式一律是"拦截 → 抛事件给外面 → 外面自己画 → 回填"。

**每个都是加一个 API 端点 + 一个事件类型,不动架构。** 碰到了再加,不用现在设计。

两个会改变 `crop_top` 的,按 §2 发 `viewport.changed` 就行,不用特殊处理:
- 视频全屏 → `crop_top` 变 0
- `Ctrl+Shift+B` 开书签栏 → `crop_top` 变大

一个小瑕疵:人按 `Ctrl+L` 会把焦点送到被裁掉的地址栏,之后键盘输入看起来"没反应"。
检测到焦点离开内容区就 `window.focus()` 抢回来,能缓解;外面 UI 上放个「恢复焦点」按钮兜底。

## 7. 结论

| 事项 | 结论 |
| --- | --- |
| 去掉 tab 条和地址栏 | **可行**,iframe 裁剪,不碰 X 不碰 WM |
| 外面感知 tab 增删改 | **可行**,`Target` 域完全够 |
| 外面控制 tab | **可行** |
| 页面内点链接开新 tab 被感知 | **可行**,还能标出 `opener` |
| 重画地址栏所需信息 | **基本可行**,缺精确进度和 favicon 事件,能绕 |
| 注入 Chrome 参数 / 开 CDP | **已实测可行**,`APP_ARGS` 环境变量,不用改镜像 |

**可行。** 先跑 §5 的实验定实现路子,再做 §3/§4 的 tab API。
