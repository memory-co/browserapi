# webmuxd 测试 — 按场景组织

> **正在往 `v2_*` 迁。** 设计在 [works/test.md](../docs/v2/works/test.md),
> 骨架在 [`v2kit.py`](v2kit.py),样例是 [`v2_cli_simple/`](v2_cli_simple/)。
> 下面那张表里的老场景还在跑,但**新加的场景照 `v2_*` 写**。

每个子目录是**一个场景**,有自己的 `README.md`(在测什么 / **不在这测什么** /
fixture 来源)和 `test.py`。相关的用例合并在一个场景下,跟「按代码模块切文件」解耦 ——
定位规则和"点下去之后发生了什么"属于不同场景,而"tab 表就是浏览器那张表"
这一条会同时用到 CDP、tab 表和事件流。

跑的是**真的 Chromium**,不 mock:这个项目的全部价值就在它和浏览器的交界处,
换成假的等于什么都没测。浏览器用的是 `webmuxd install` 下的那个**钉死版本**
([`config.py`](../webmuxd/config.py) 的 `PINNED`)。

## 场景一览

| 目录 | 测什么 |
|---|---|
| [`one_endpoint/`](one_endpoint/) | **runtime 只做一件事**:给出一个 CDP 端点。不可用时抛不降级、端口不替你换、浏览器版本钉死 |
| [`pixels_on_a_wire/`](pixels_on_a_wire/) | **画面是我们自己产的**:帧头形状、两个 ack 环解耦、切 tab 时 targetId 真的变了、只读是服务端丢弃 |
| [`pixels_from_xpra/`](pixels_from_xpra/) | **换一条像素来源,别的一律不动**:上行白名单是闭集(输入包一个过不去)、xpra 下不发 `startScreencast` 但照发 `activateTarget`、rencodeplus 两边对得上、**观看页的脚本能被解析** |
| [`no_desktop/`](no_desktop/) | **六类原生 UI 用 CDP 收回来**:拦得下来、回填得进去、超时不静默。判据是页面自己动了,不是我们收到了事件 |
| [`tab_identity/`](tab_identity/) | **tab 表就是 target 表**:`t_N` 不复用、`reason` 靠 `openerId` 分、关掉和被挤掉是两回事、先建后挤 |
| [`the_extension/`](the_extension/) | **那个扩展装上了没有、在不在干活**:判据是它**自报家门**的那个标记(不靠文件名、不靠"我们传了参数"),以及 `Browser.getWindowForTarget` 给的 `windowId`。顺带盯住权限面:只要 `tabs`、**没有 host 权限、没有内容脚本** |
| [`who_is_in_front/`](who_is_in_front/) | **浏览器把哪一页放在前台,那就是 `active`** —— 那张表里原来唯一一本"我们自己记的账"。我们的命令只是信号,`activate()` **返回即为真**;第三方抢走前台我们跟着走。判据取自页面那一侧的 `visibilityState`,由第二条 CDP 读回来 |
| [`pointing_at_things/`](pointing_at_things/) | **按人看得见的字找**:分档匹配命中即停、有歧义给候选不替你挑、找不到也要说这页上有什么 |
| [`doing_and_seeing/`](doing_and_seeing/) | **做一下再看看**:变化变成一句人话(没变就不说)、观测一次给全、标注层用完就撤 |
| [`the_scrollback/`](the_scrollback/) | **日志是 scrollback 不是事件流**:三类、按条数切、`seq` 跨重启、半行不毁全份、能打包带走 |
| [`installing/`](installing/) | **只回答两个问题**:下得到那个浏览器吗、依赖齐吗。幂等、下不到就不写那个键、记录不是配置文件 |
| [`the_http_face/`](the_http_face/) | **HTTP 面存在的唯一理由是可独立验证**:形状和 lib 一一对上、不做 lib 没有的事、动作串行遇错即停、忙就 409 不排队 |

## v2 那一套

**名字是 `v2_<面>_<场景>`** —— "面"是从哪个口子进去的
([works/test.md §2](../docs/v2/works/test.md))。

| 目录 | 面 | 测什么 |
|---|---|---|
| [`v2_cli_simple/`](v2_cli_simple/) | cli | **一条完整的路**:起服务 → 开 session → 打开百度 → 搜一个词 → 看到结果。走 **VNC(有头)**,顺带验那条腿 |
| [`v2_cli_new_tab/`](v2_cli_new_tab/) | cli | **点一个 `target=_blank` 的链接,弹出来的是个 tab**:opener 认得爹、**前台跟着浏览器走**(它把新那个开在前台)。走 **JPG(无头)**,验另一条腿 |
| [`v2_cli_session/`](v2_cli_session/) | cli | **两个 session,各干各的**:各去各的地址、号不串、日志不串、**关掉一个另一个照常能用**。替掉了 `session_identity/` |
| [`v2_refs/`](v2_refs/) | 数据 | **`@e1` 这个号的规矩**,不起浏览器:四种失败各说各的话、只增不重用、**不跨文档** |
| [`v2_browser_simple/`](v2_browser_simple/) | browser | **一个真人打开观看页会撞上什么**:Playwright 起一个真浏览器,点一下、敲几个键、把窗口拉小 —— 里面真的动了,观看页一条错都没报 |
| [`v2_browser_modes/`](v2_browser_modes/) | browser | **换画面,而且换得回来**:VNC → JPG → VNC。判据是画布上真的有东西(数颜色),不是"有尺寸"。**这一条是被一个 bug 逼出来的** —— 切回 VNC 曾经什么都不做,还不报错 |
| [`v2_browser_reconnect/`](v2_browser_reconnect/) | browser | **网抖一下,画面回不回得来**。挖出 `/channel/xpra` 根本不重连 —— VNC 下网一抖画面就永远停在最后一帧。判据是**新帧在流**,不是"画面上有东西" |
| [`v2_browser_new_tab/`](v2_browser_new_tab/) | browser | **那条 tab 条跟不跟得上**:人在画面上点 `target=_blank`、点 tab、点 `×`、点 `＋`、地址栏敲回车 —— 每一下之后**六样一起看**,而且其中两样**不来自我们那张表**(页面的 `visibilityState`、画面上到底是哪一页)。最后一条跑 **VNC**:**同一个链接三种点法** —— 普通左键前台开、Ctrl+左键和中键后台开,画面各自跟对。这条只能在 VNC 上验,JPG 下画面冻在上一帧,判据穿不透 |

三条规矩写在 [`v2kit.py`](v2kit.py) 开头:

1. **动作从 CLI 进,而且真起一个进程** —— `python -m webmuxd`,不是 import `main()`
2. **观察也从 CLI 进** —— `snapshot` 给的 `@e1` 就是页面结构,不往页面里塞 JS。
   **非塞 JS 不可的时候,先问是不是缺了个命令**
3. **"人看到了什么"从一个真的浏览器来** —— 协议那层接 `/channel/cdp` 看,
   整页那层用 Playwright 起一个真浏览器打开观看页。**它能看到我们看不到的:
   观看页自己报的错**

> **删掉的四个**(git 历史里还在):
>
> - `the_docs_are_true/` —— 检查文档链接和文档里抄的数字。**那是给文档做的
>   lint,不是给这个项目做的测试**:它红的时候多半是有人改了个标题
> - `cli_shell/` —— 测的东西对,但它 in-process 调 `main()`。
>   **`v2_cli_*` 从真进程进,把它验的那几条连同更多一起验了**
> - `errors_are_a_contract/` · `chrome_facts/` —— 贴着代码量异常映射和 CDP 行为。
>   判据见 [works/test.md §1](../docs/v2/works/test.md)
> - `session_identity/` —— 测 SDK 那三个对象的语义。
>   [`v2_cli_session/`](v2_cli_session/) 从 CLI 那一面接过了"两个 session
>   互不影响"这一半;**另一半(对象幂等、属性读内存、`act()` 不抛)真的没了**,
>   要补该开一条 `v2_sdk_*`

## 共享 fixture / helper

- `v2kit.py` —— v2 那一套的骨架:`server()` 起一个真 server、
  `Cli` 的 `run/out/api/snap/one`、`Viewer`(那条 WS)、
  `human()`(Playwright 起的真浏览器)
- `conftest.py` —— `chromium_endpoint`(一个真的 headless Chromium,session 级)、
  CDP 连接、临时数据目录
> v2 把容器整条去掉了([works/07 §2](../docs/v2/works/07-runtime.md)),所以那两个
> 镜像场景和它们的 `image_conftest.py` 一起删了 —— 它们测的是 wrapper 镜像,
> 而现在没有镜像。git 历史里还在。

## 跑

```bash
webmuxd install            # 一次就够 —— 测试用的就是它下的那个浏览器
pytest -q
pytest -q tests/pointing_at_things
```

**没有"要在宿主机上单跑"的场景了** —— 全部在同一个环境里跑得起来。
要浏览器的那几个场景没有浏览器就跳过,不是失败。

## 加新场景

1. 新目录 `tests/场景名/`,放 `__init__.py`
2. 写 `README.md`:**测什么 / 不测什么 / fixture 来源**。
   "不测什么"那节别省 —— 它是给下一个人看的路标,省掉之后同一条断言会在三个场景里各写一遍
3. 写 `test.py`,开头一行 `"""场景名 — 一句话. See README.md."""`
4. 不用登记,pytest 自动收(`python_files` 已含 `test.py`)

用例名写成句子(`test_the_env_names_come_from_the_image_not_from_us`),
失败时那一行本身就是报告。
