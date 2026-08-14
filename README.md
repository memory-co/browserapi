# webmuxd

[![PyPI](https://img.shields.io/pypi/v/webmuxd)](https://pypi.org/project/webmuxd/)
[![Python](https://img.shields.io/pypi/pyversions/webmuxd)](https://pypi.org/project/webmuxd/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**Chromium 做成一个 Python 库:活得比连接久、程序能驱动、人能用浏览器打开的浏览器。**

**简体中文** · [GitHub](https://github.com/memory-co/webmuxd) · [CNB](https://cnb.cool/agentuse/webmuxd)(国内)

**webmuxd 是一个 `*muxd` 组件** —— 一扇 HTTP 上的窗给人,一个 Python 把手给程序。
这一族的规范定在 [shellbase](https://github.com/memory-co/shellbase):
[new-interface](https://github.com/memory-co/shellbase/blob/main/docs/v1/new-interface.md)(为什么是这个形状) ·
[muxd-spec](https://github.com/memory-co/shellbase/blob/main/docs/v1/muxd-spec.md)(算不算一个组件) ·
姊妹项目 [tmuxd](https://github.com/memory-co/tmuxd)(终端那一块)

---

无头浏览器能被程序驱动,但**人看不见**;远程桌面里的浏览器人能看见,
但**程序碰不到**。于是排查一次登录失败要来回切:脚本跑一遍、截图存下来、
自己打开看、改一行再跑一遍。

webmuxd 让这两件事落在**同一个浏览器**上:

```python
from webmuxd import Webmuxd

web  = Webmuxd(user="claudecode")                            # 空壳,不起任何东西
sess = web.session(id="work", port=7900, vnc_port=8090)      # 这行才起一个浏览器
tab  = sess.open("https://example.com")

tab.type("手机号", "13800000000")
tab.click("提交订单")                                         # 按人看得见的字,不写选择器

print(sess.vnc_url, sess.vnc_user, sess.vnc_password)        # 人从这儿进去看
```

那个地址发给谁,谁的浏览器里就是**这个浏览器** —— 看得见,也能直接伸手接管。
程序点了什么人立刻看见,人改了什么程序下一次读到的就是改完的。
**不是两份状态,是一份。**

## 快速开始

要 `docker`,别的都不用 —— Chromium 在镜像里。

```bash
pip install webmuxd
webmuxd install          # 只做两件事:确认 docker 能用、镜像拉不拉得到
```

### 当库用

```python
from webmuxd import Webmuxd

web = Webmuxd()
sess = web.session(id="work", port=7900, vnc_port=8090)
tab = sess.open("https://news.ycombinator.com")

print(tab.observe().as_prompt())      # 元素表,直接喂多模态模型
tab.click("new")
```

`session(id=...)` 是幂等的 —— 同一个 id 再调一次拿到同一个,不会起第二个浏览器。
**端口必须你给**:端口是部署决定的,替你猜一个只会让配置和实际对不上。

### 用命令行

```bash
webmuxd new      -s work -p 7900 --vnc-port 8090
webmuxd new-tab  -t work -u https://example.com
webmuxd click    -t work "Learn more"
webmuxd observe  -t work                  # 喂给模型的元素表
webmuxd log      -t work                  # 它都干了什么
webmuxd kill     -t work
```

**跑起来之后,用浏览器打开 `webmuxd new` 打印的那个画面地址** —— 然后在另一边敲
`webmuxd click`,页面会在你眼前跳过去。整条链路通没通,这一眼就看出来了。

完整走一遍见 [QUICKSTART.md](QUICKSTART.md)。

## 它和别的东西不一样在哪

- **按人看得见的字操作。** `click("提交订单")`,不写选择器。分档匹配(精确 → 子串 →
  忽略大小写),**有歧义就给候选,绝不替你挑一个** —— 挑错了你永远不会知道。
- **"看见"= 元素表 + 标注截图。** `observe()` 一次给全,直接喂多模态模型;
  拿不到的东西写进 `notes`,而不是假装看全了。
- **tab 表就是浏览器那张表。** 不是黑盒:`reason` 分得清是人点开的还是代码开的
  (靠 CDP 的 `openerId`);逃生舱是**你自己拿 DevTools 连上去**,看到的和它一样。
- **日志是 scrollback,不是事件流。** 每一步看到什么、做了什么、页面变成什么样,
  一个 JSONL 按条数切 —— 给人和模型回看的。
- **`act()` 不抛异常。** 写 agent 循环时要把候选喂回模型自我纠正,而不是被异常打断;
  快捷方法(`click` / `type`)则照抛。
- **关掉网页,浏览器照常在跑。** 门面短命,屋子长命。

## 两个端点,别的都不算

```
一个画面端口   ← 给人:浏览器打开就能看,能上手
一个 CDP 端点  ← 给代码:webmuxd 订阅它
```

产出这两样的东西就是一个 runtime,**是不是容器不在契约里**:

| | 起什么 | 用在哪 |
| --- | --- | --- |
| `container`(默认) | 一个现成的浏览器镜像 | 生产。有隔离,画面是完整桌面 |
| `process` | 本机 chromium + Xvnc | 开发、CI。秒起,但没有隔离 |
| `remote` | 什么都不起,两个端点你给 | 云浏览器、别人机器上那个 |

这条线以上的代码**没有任何一处 `if runtime ==`** —— 为什么能做到,见
[works/08](docs/v1/works/08-browser-runtime.md)。

## 镜像

两个现成的,`webmuxd install` 会把默认那个准备好:

| | 挑它的理由 | 代价 |
| --- | --- | --- |
| `kasmweb-chromium`(默认) | **画面最好** | `--network host` 下一台机器只能跑一个 |
| `jlesage-chromium` | **能一机多开** | 画面差一点 |

```bash
docker pull ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0         # 海外
docker pull docker.cnb.cool/agentuse/webmuxd/kasmweb-chromium:1.18.0  # 国内
```

它们是在 kasm / jlesage 原厂镜像上**加一层**:补上 CDP 端点(Chromium 把调试口
绑死在容器内的 loopback,`docker -p` 够不着),并把端口变量名统一成
`WEBMUXD_WINDOW_PORT` / `WEBMUXD_CDP_PORT`。

**换镜像不用改 webmuxd 的代码** —— 它读镜像的 `webmuxd.*` 标签认它,不认名字。
自己加第三个镜像怎么做,见 [docker/](docker/README.md)。

## 依赖

| | | |
| --- | --- | --- |
| **Docker** | 任意近版 | `container` runtime 要它 |
| **Python** | ≥ 3.10 | |
| **系统** | Linux | 容器共享 network namespace,这是 Linux 的东西 |

`process` runtime 另外要本机有 `chromium`(以及 `Xvnc` —— 没有就只有 API 没有画面,
**这件事它会明说**,而不是给你一个连不上的地址)。

镜像里是 **Chromium 不是 Chrome**:Chrome 是专有软件、再分发受限。代价是不带
H.264 / AAC,少数只有这两种编码的视频放不了。

## 开发

```bash
docker build -t webmuxd-dev docker/dev/
docker run --rm -v "$PWD":/src webmuxd-dev pytest -q
```

测试跑的是**真的 Chromium**,不 mock —— 这个项目的全部价值就在它和浏览器的交界处,
换成假的等于什么都没测。用例[按场景组织](tests/README.md),不按代码模块:
`pointing_at_things/` 是"按字找东西",`chrome_facts/` 是"我们对 CDP 的假设逐条量过"
(换 Chromium 大版本先跑它)。

两个镜像各有一个场景,真的 `docker run`,要在宿主机上跑:

```bash
pytest tests/image_kasmweb tests/image_jlesage
```

## 文档

| | |
| --- | --- |
| [QUICKSTART.md](QUICKSTART.md) | 完整跑一遍 |
| [`docs/v1/sdk`](docs/v1/sdk/) | Python 包 —— **主体**,行为定义在这儿 |
| [`docs/v1/api`](docs/v1/api/) | HTTP + WS 的线上格式 —— sdk 的导出面 |
| [`docs/v1/cli`](docs/v1/cli/) | `webmuxd` 命令,照着 tmux 设计 |
| [`docs/v1/works`](docs/v1/works/) | **为什么这么做** —— 设计稿和实测记录 |
| [docker/](docker/README.md) | 镜像怎么用、怎么加一个新的 |

## 许可

Apache-2.0,见 [LICENSE](LICENSE)。

webmuxd 把 [Chromium](https://www.chromium.org/)(BSD)当外部程序驱动,
画面那一半用 [kasmweb](https://hub.docker.com/r/kasmweb/chromium) 和
[jlesage](https://hub.docker.com/r/jlesage/chromium) 的镜像 ——
**不改动、不重新发行它们的源码**,只在上面加一薄层。
