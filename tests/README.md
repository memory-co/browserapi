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
| [`two_endpoints/`](two_endpoints/) | **runtime 只做一件事**:把机器变成一个 CDP 端点 + 一个画面口。不可用时抛不降级、端口不替你换、容器那条的变量名全来自镜像标签 |
| [`image_kasmweb/`](image_kasmweb/) | **我们给 kasm 加的那层成立吗**:标签说清了 profile、CDP 不用 exec 就出来了、窗还是原来的样子 |
| [`image_jlesage/`](image_jlesage/) | **这层几乎没加东西,那它加了什么**:标签的值和 kasm 全不同、中继是底座自己的、**两个容器能共享 host netns** |
| [`tab_identity/`](tab_identity/) | **tab 表就是 target 表**:`t_N` 不复用、`reason` 靠 `openerId` 分、关掉和被挤掉是两回事、先建后挤 |
| [`pointing_at_things/`](pointing_at_things/) | **按人看得见的字找**:分档匹配命中即停、有歧义给候选不替你挑、找不到也要说这页上有什么 |
| [`doing_and_seeing/`](doing_and_seeing/) | **做一下再看看**:变化变成一句人话(没变就不说)、观测一次给全、标注层用完就撤 |
| [`the_scrollback/`](the_scrollback/) | **日志是 scrollback 不是事件流**:三类、按条数切、`seq` 跨重启、半行不毁全份、能打包带走 |
| [`session_identity/`](session_identity/) | **id 说了算端口你给**:空壳管理实例、幂等返回同一个对象、属性读内存不发请求、`act()` 不抛而快捷方法抛 |
| [`cli_shell/`](cli_shell/) | **CLI 照着 tmux 长**:退出码是接口、`new` 幂等、文件只是线索活没活要现探、定位失败在终端里列候选 |
| [`installing/`](installing/) | **只回答两个问题**:docker 能用吗、拉得到镜像吗。不 build 不预拉、拉不到就不写那个键、配置不得改变库的行为 |
| [`errors_are_a_contract/`](errors_are_a_contract/) | **错误分类指向不同的下一步**:每个线上 code 一个类、不认识的按状态兜底而不是 `KeyError`、半个响应体也能变成异常 |
| [`chrome_facts/`](chrome_facts/) | **我们对 Chromium 的假设,逐条量过**:四种开 tab 的方式全带 `openerId`、`setDiscoverTargets` 会补已存在的 target。**换大版本先跑这个** |
| [`the_http_face/`](the_http_face/) | **HTTP 面存在的唯一理由是可独立验证**:形状和 lib 一一对上、不做 lib 没有的事、动作串行遇错即停、忙就 409 不排队 |

## 共享 fixture / helper

- `conftest.py` —— `chromium_endpoint`(一个真的 headless Chromium,session 级)、
  CDP 连接、临时数据目录
- `image_conftest.py` —— 两个镜像场景专用:`need_image`(**没这个镜像就跳过,
  不是失败** —— 它得 build 出来才有)、`session_on`(真起容器 + sessiond,
  `with` 退出时收干净)

## 跑

```bash
docker run --rm -v "$PWD":/src webmuxd-dev pytest -q       # 除镜像场景外的全部
docker run --rm -v "$PWD":/src webmuxd-dev pytest -q tests/pointing_at_things
```

**两个镜像场景要在宿主机上跑**,因为它们要 `docker run`(dev 镜像里没有 docker):

```bash
docker build -t webmuxd/kasmweb-chromium:1.18.0 docker/kasmweb-chromium/
docker build -t webmuxd/jlesage-chromium:latest docker/jlesage-chromium/
pytest tests/image_kasmweb tests/image_jlesage
```

镜像没 build 出来时它们**自动跳过**,不会红。

## 加新场景

1. 新目录 `tests/场景名/`,放 `__init__.py`
2. 写 `README.md`:**测什么 / 不测什么 / fixture 来源**。
   "不测什么"那节别省 —— 它是给下一个人看的路标,省掉之后同一条断言会在三个场景里各写一遍
3. 写 `test.py`,开头一行 `"""场景名 — 一句话. See README.md."""`
4. 不用登记,pytest 自动收(`python_files` 已含 `test.py`)

用例名写成句子(`test_the_env_names_come_from_the_image_not_from_us`),
失败时那一行本身就是报告。
