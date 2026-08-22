# webmuxd 测试 — 按场景组织

> **正在往 `v2_*` 迁。** 新的一套从 CLI 进、真起进程、用 `snapshot` 观察,
> 骨架在 [`v2kit.py`](v2kit.py),样例是 [`v2_simple/`](v2_simple/)。
> 下面那张表里的老场景还在跑,但**新加的场景照 `v2_*` 写**。

每个子目录是**一个场景**,有自己的 `README.md`(在测什么 / **不在这测什么** /
fixture 来源)和 `test.py`。相关的用例合并在一个场景下,跟「按代码模块切文件」解耦 ——
定位规则和"点下去之后发生了什么"属于不同场景,而"tab 表就是浏览器那张表"
这一条会同时用到 CDP、tab 表和事件流。

跑的是**真的 Chromium**,不 mock:这个项目的全部价值就在它和浏览器的交界处,
换成假的等于什么都没测。浏览器用的是 `webmuxd install` 下的那个**钉死版本** ——
所以"换 Chromium 大版本先跑 `chrome_facts`"是可执行的,不是一句口号。

## 场景一览

| 目录 | 测什么 |
|---|---|
| [`one_endpoint/`](one_endpoint/) | **runtime 只做一件事**:给出一个 CDP 端点。不可用时抛不降级、端口不替你换、浏览器版本钉死 |
| [`pixels_on_a_wire/`](pixels_on_a_wire/) | **画面是我们自己产的**:帧头形状、两个 ack 环解耦、切 tab 时 targetId 真的变了、只读是服务端丢弃 |
| [`pixels_from_xpra/`](pixels_from_xpra/) | **换一条像素来源,别的一律不动**:上行白名单是闭集(输入包一个过不去)、xpra 下不发 `startScreencast` 但照发 `activateTarget`、rencodeplus 两边对得上、**观看页的脚本能被解析** |
| [`no_desktop/`](no_desktop/) | **六类原生 UI 用 CDP 收回来**:拦得下来、回填得进去、超时不静默。判据是页面自己动了,不是我们收到了事件 |
| [`tab_identity/`](tab_identity/) | **tab 表就是 target 表**:`t_N` 不复用、`reason` 靠 `openerId` 分、关掉和被挤掉是两回事、先建后挤 |
| [`pointing_at_things/`](pointing_at_things/) | **按人看得见的字找**:分档匹配命中即停、有歧义给候选不替你挑、找不到也要说这页上有什么 |
| [`doing_and_seeing/`](doing_and_seeing/) | **做一下再看看**:变化变成一句人话(没变就不说)、观测一次给全、标注层用完就撤 |
| [`the_scrollback/`](the_scrollback/) | **日志是 scrollback 不是事件流**:三类、按条数切、`seq` 跨重启、半行不毁全份、能打包带走 |
| [`session_identity/`](session_identity/) | **id 说了算端口你给**:空壳管理实例、幂等返回同一个对象、属性读内存不发请求、`act()` 不抛而快捷方法抛 |
| [`cli_shell/`](cli_shell/) | **CLI 照着 tmux 长**:退出码是接口、`new` 幂等、文件只是线索活没活要现探、定位失败在终端里列候选 |
| [`installing/`](installing/) | **只回答两个问题**:下得到那个浏览器吗、依赖齐吗。幂等、下不到就不写那个键、记录不是配置文件 |
| [`errors_are_a_contract/`](errors_are_a_contract/) | **错误分类指向不同的下一步**:每个线上 code 一个类、不认识的按状态兜底而不是 `KeyError`、半个响应体也能变成异常 |
| [`chrome_facts/`](chrome_facts/) | **我们对 Chromium 的假设,逐条量过**:四种开 tab 的方式全带 `openerId`、`setDiscoverTargets` 会补已存在的 target。**换大版本先跑这个** |
| [`the_http_face/`](the_http_face/) | **HTTP 面存在的唯一理由是可独立验证**:形状和 lib 一一对上、不做 lib 没有的事、动作串行遇错即停、忙就 409 不排队 |

## v2 那一套

| 目录 | 测什么 |
|---|---|
| [`v2_simple/`](v2_simple/) | **一条完整的路**:起服务 → 开 session → 打开百度 → 搜一个词 → 看到结果。走 **VNC(有头)**,顺带验那条腿 |
| [`v2_new_tab/`](v2_new_tab/) | **点一个 `target=_blank` 的链接,弹出来的是个 tab**:opener 认得爹、焦点不跟过去、新 tab 上照样能用。走 **JPG(无头)**,验另一条腿 |
| [`v2_refs/`](v2_refs/) | **`@e1` 这个号的规矩**,只有数据不起浏览器:只增不重用、四种失败各说各的话 |

三条规矩写在 [`v2kit.py`](v2kit.py) 开头:

1. **动作从 CLI 进,而且真起一个进程** —— `python -m webmuxd`,不是 import `main()`
2. **观察也从 CLI 进** —— `snapshot` 给的 `@e1` 就是页面结构,不往页面里塞 JS
3. **只有"人看到了什么"从观看端来** —— 画面帧和光标从 `/channel/cdp` 看

> 删掉的:`the_docs_are_true/`。它检查文档链接和文档里抄的数字 ——
> **那是给文档做的 lint,不是给这个项目做的测试**。
> 一条断言只有在"代码错了它会红"的时候才值钱,而它红的时候多半是有人改了个标题。
> git 历史里还在。

## 共享 fixture / helper

- `v2kit.py` —— v2 那一套的骨架:`server()` 起一个真 server、
  `Cli` 的 `run/out/api/snap/one`、`Viewer`
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
