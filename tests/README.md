# webmuxd 测试 — 按场景组织

每个子目录是**一个场景**,有自己的 `README.md`(在测什么 / **不在这测什么** /
fixture 来源)和 `test.py`。相关的用例合并在一个场景下,跟「按代码模块切文件」解耦 ——
定位规则和"点下去之后发生了什么"属于不同场景,而"tab 表就是浏览器那张表"
这一条会同时用到 CDP、tab 表和事件流。

跑的是**真的 Chromium**,不 mock:这个项目的全部价值就在它和浏览器的交界处,
换成假的等于什么都没测。两个镜像场景更进一步,真的 `docker run`。

## 场景一览

| 目录 | 测什么 |
|---|---|
| [`one_endpoint/`](one_endpoint/) | **runtime 只做一件事**:给出一个 CDP 端点。不可用时抛不降级、端口不替你换、浏览器版本钉死 |
| [`pixels_on_a_wire/`](pixels_on_a_wire/) | **画面是我们自己产的**:帧头形状、两个 ack 环解耦、切 tab 时 targetId 真的变了、只读是服务端丢弃 |
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

## 共享 fixture / helper

- `conftest.py` —— `chromium_endpoint`(一个真的 headless Chromium,session 级)、
  CDP 连接、临时数据目录
> v2 把容器整条去掉了,所以 `image_kasmweb/` `image_jlesage/` `image_conftest.py`
> 一起删了 —— 它们测的是给 kasm / jlesage 加的那层 wrapper,而 v2 不用镜像
> ([works/07 §2](../docs/v2/works/07-runtime.md))。git 历史里还在。

## 跑

```bash
docker run --rm -v "$PWD":/src webmuxd-dev pytest -q       # 全部
docker run --rm -v "$PWD":/src webmuxd-dev pytest -q tests/pointing_at_things
```

**不再需要在宿主机上单跑任何场景** —— v2 不 `docker run`,所有场景都在同一个
环境里跑得起来。`one_endpoint` 和 `pixels_on_a_wire` 要一个真浏览器,
没有就跳过(不是失败)。

## 加新场景

1. 新目录 `tests/场景名/`,放 `__init__.py`
2. 写 `README.md`:**测什么 / 不测什么 / fixture 来源**。
   "不测什么"那节别省 —— 它是给下一个人看的路标,省掉之后同一条断言会在三个场景里各写一遍
3. 写 `test.py`,开头一行 `"""场景名 — 一句话. See README.md."""`
4. 不用登记,pytest 自动收(`python_files` 已含 `test.py`)

用例名写成句子(`test_the_env_names_come_from_the_image_not_from_us`),
失败时那一行本身就是报告。
