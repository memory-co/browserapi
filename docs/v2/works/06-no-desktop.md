# 06 · 没有桌面之后

**一句话**:六类原生 UI 在 headless 里根本不渲染,必须一条条用 CDP 拦下来、
抛事件给外面、由外面画、再回填。**这是 v2 唯一的真实工作量。**

## 1. 从"以后按需加"变成"必须做"

v1 [works/04 §6](../../v1/works/04-chrome-ui-externalization.md#6-顺带会掉出来的东西不影响架构以后按需加)
已经点过这批东西,当时的定性是:

> tab 条和地址栏被裁掉之后,一批挂在工具栏上的原生 UI 会变成"看不见但仍然阻塞"。
> …**每个都是加一个 API 端点 + 一个事件类型,不动架构。碰到了再加,不用现在设计。**

那个判断在 v1 成立,因为**桌面还在**:裁 iframe 只是把它挪出可视区,人把 iframe
往上滚一点、或者换个不裁的视图,对话框就露出来了 —— 有兜底。

v2 没有兜底。screencast 拍的是页面内容,浏览器自己的 UI **一个像素都不会出现在帧里**。
不拦,页面就是**静止在那儿**,而人看不出为什么。

**但它比 v1 干净**:v1 是"有时候能看见有时候看不见"的中间态,v2 是**确定的、
唯一的路径** —— 全部走 CDP,没有二义性,行为可测。

## 2. 六类,逐条

| 原生 UI | CDP 拦截 | 回填 |
| --- | --- | --- |
| **JS 对话框**<br>`alert` / `confirm` / `prompt` / `beforeunload` | `Page.javascriptDialogOpening` | `Page.handleJavaScriptDialog {accept, promptText}` |
| **文件选择框** | `Page.setInterceptFileChooserDialog` → `Page.fileChooserOpened` | `DOM.setFileInputFiles` |
| **下载** | `Browser.setDownloadBehavior` + `Browser.downloadWillBegin` / `downloadProgress` | 文件落到 session 目录,API 取 |
| **权限请求**<br>定位 / 通知 / 摄像头 / 剪贴板 | 不弹框,默认拒绝 | `Browser.grantPermissions` / `resetPermissions` 显式给 |
| **HTTP Basic 认证** | `Fetch.enable {handleAuthRequests}` → `Fetch.authRequired` | `Fetch.continueWithAuth` |
| **PDF / 浏览器内置查看器** | headless 无内置查看器 | 当下载处理;要看内容用 `Page.printToPDF` 反向 |

每一条都是**一个事件 + 一个端点**,不动架构 —— v1 那句判断在这一点上仍然对。

### 三条共同的规矩

**① 不替用户决定。** `alert` 不自动 accept,文件选择不自动填,权限不自动 grant。
一律抛事件出去等回填 —— 因为这些**本来就是人的决定**,替他做了,自动化脚本
就会在"以为点了确定"和"其实没点"之间产生看不见的分歧。

**② 有超时,而且超时是显式的。** 拦下来没人回填,页面就永远卡着。
每类都有默认超时和默认动作(`alert` → dismiss、文件选择 → 取消、
认证 → 取消),超时**写进日志**,不静默。

**③ 内置页面要能画它们。** [04 §2](04-one-port.md#2-get--是内置的但它不是界面)
说内置页面不带产品决策,但这六类是**协议的一部分**,不是产品功能:
不画,人在那个页面上就会遇到"点了没反应"。

## 3. 日志里必须看得见

v1 的操作日志是"每一步看到什么、做了什么、页面变成什么样"的 scrollback
([v1/works/03](../../v1/works/03-log.md))。这六类事件**必须进去**,
因为它们是页面停住的唯一解释:

```jsonc
{"t":"...","kind":"dialog","subtype":"confirm","text":"确定要删除吗?","state":"pending"}
{"t":"...","kind":"dialog","subtype":"confirm","action":"accept","by":"user:claudecode"}
{"t":"...","kind":"download","file":"报表.xlsx","bytes":48213,"state":"done"}
{"t":"...","kind":"permission","name":"geolocation","action":"deny","by":"default"}
```

**「模型跑着跑着卡住了」的排查路径**,在 v2 里第一站就是这几条 ——
没有它们,现象是"observe 返回的页面一直没变",看不出是网络慢还是有个 confirm 挡着。

## 4. 还有一类:页面里的浏览器行为

不是对话框,但同样是"桌面负责的事":

| | v1(有桌面) | v2 |
| --- | --- | --- |
| **新窗口 / popup** | 独立 X 窗口,盖在画面上([v1/works/07](../../v1/works/07-popup-windows.md)) | 就是一个 tab([05 §4](05-active-tab.md#4-popup-不再是特殊情况)) |
| **全屏**(视频) | 改变 `crop_top`,要发 `viewport.changed` | 页面内的事,帧尺寸不变,**不用管** |
| **打印** | 系统打印对话框 | `Page.printToPDF`,当下载处理 |
| **拖放文件进页面** | 桌面拖放 | `Input.dispatchDragEvent` + 文件走上传端点 |
| **右键菜单** | 浏览器的原生菜单 | 没有。**内置页面自己画**(复制 / 粘贴 / 在新 tab 打开链接) |

右键菜单那条要说明白:`contextmenu` 事件会传给远端页面(自定义右键菜单的网站正常工作),
但浏览器**默认**的那个菜单不存在了 —— 它本来就是 chrome UI,不是页面内容。

## 5. 排期:不是全都要一次做完

按"不做会卡住人"排序:

| 优先级 | 做什么 | 不做的后果 |
| --- | --- | --- |
| **必须** | JS 对话框 | 任何 `confirm` 都会让页面永久卡住,而且看不出来 |
| **必须** | 下载 | 点了下载什么都不发生,文件在容器里没人知道 |
| **必须** | 文件选择 | 上传类流程完全走不通 |
| 应该 | Basic 认证 | 遇到就是白屏,但比较少见 |
| 应该 | 权限 | 默认拒绝是安全的默认,不做也不会卡住 |
| 可以晚 | 右键菜单 / 拖放 / 打印 | 有替代路径(API / 快捷键) |

前三条是 v2 **能不能宣布可用**的门槛,后面的按需。

## 6. ↔ 别处

| | |
| --- | --- |
| 这批东西在 v1 的原始记录 | [v1/works/04 §6](../../v1/works/04-chrome-ui-externalization.md#6-顺带会掉出来的东西不影响架构以后按需加) |
| 日志格式 | [v1/works/03](../../v1/works/03-log.md) —— **原样有效** |
| popup 为什么不再特殊 | [05 §4](05-active-tab.md#4-popup-不再是特殊情况) |
| 输入通道 | [03](03-input.md) |
