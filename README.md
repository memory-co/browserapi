# webmuxd

[![PyPI](https://img.shields.io/pypi/v/webmuxd)](https://pypi.org/project/webmuxd/)
[![Python](https://img.shields.io/pypi/pyversions/webmuxd)](https://pypi.org/project/webmuxd/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

**Chromium 做成一个 Python 库:活得比连接久、程序能驱动、人能用浏览器打开的浏览器。**

**简体中文** · [更新日志](CHANGELOG.md) · [GitHub](https://github.com/memory-co/webmuxd) · [CNB](https://cnb.cool/agentuse/webmuxd)(国内)

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

web  = Webmuxd(user="claudecode")            # 空壳,不起任何东西
sess = web.session(id="work", port=7900)     # 这行才起一个浏览器
tab  = sess.open("https://example.com")

tab.type("手机号", "13800000000")
tab.click("提交订单")                         # 按人看得见的字,不写选择器

print(sess.view_url)                         # 人从这儿进去看,浏览器打开就是
```

那个地址发给谁,谁的浏览器里就是**这个浏览器** —— 看得见,也能直接伸手接管。
程序点了什么人立刻看见,人改了什么程序下一次读到的就是改完的。
**不是两份状态,是一份。**

## 快速开始

只要 Python。**不要 docker,也不用你自己装浏览器。**

```bash
pip install webmuxd
webmuxd install          # 下浏览器 + 把环境弄齐(有 root 会顺手装依赖)
```

`install` 把浏览器放进 `~/.cache/webmuxd/`,路径记进 `~/.webmuxd.json`,
并且探一遍共享库、中文字体、以及**画面默认走的 xpra**。
**有 root 就直接装上,没 root 就打出完整的那行命令** —— 它不会探到缺了却不管。
**幂等** —— 再跑一次就是重新探一遍,所以"检查"和"安装"是同一个命令。

### 当库用

```python
from webmuxd import Webmuxd

web = Webmuxd()
sess = web.session(id="work", port=7900)
tab = sess.open("https://news.ycombinator.com")

print(tab.observe().as_prompt())      # 元素表,直接喂多模态模型
tab.click("new")
```

`session(id=...)` 是幂等的 —— 同一个 id 再调一次拿到同一个,不会起第二个浏览器。
**端口必须你给**:端口是部署决定的,替你猜一个只会让配置和实际对不上。

### 用命令行

```bash
webmuxd new      --id work --port 7900
webmuxd new-tab  -t work -u https://example.com
webmuxd click    -t work "Learn more"
webmuxd observe  -t work                  # 喂给模型的元素表
webmuxd log      -t work                  # 它都干了什么
webmuxd kill     -t work
```

**跑起来之后,用浏览器打开 `webmuxd new` 打印的那个地址** —— 然后在另一边敲
`webmuxd click`,页面会在你眼前跳过去。整条链路通没通,这一眼就看出来了。

完整走一遍见 [QUICKSTART.md](QUICKSTART.md)。

## 它和别的东西不一样在哪

- **画面是自己产的。** 不是 VNC,不是桌面 —— 人的鼠标键盘被归一化后翻译成
  CDP `Input.*` 打回去,所以画面里**只有页面内容**,tab 条和地址栏由你自己画
  ([docs/v2/works/01](docs/v2/works/01-frame-source.md))。
  像素默认由 xpra 出(按区域编码,滚动时零字节搬像素),装不上时退到
  CDP 截屏那条 —— **两条路换的只有像素从哪来**,输入、只读、tab、原生 UI
  一模一样([works/11](docs/v2/works/c-pixels.md))。
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

## 一个口,别的都不算

```
http://host:7900/           ← 人:浏览器打开就能看,能上手
http://host:7900/api/…      ← 代码:同一个口
ws://host:7900/api/view     ← 帧下行 + 输入上行
ws://host:7900/xpra         ← 换了 xpra 出帧时,画面走这条(输入仍然走上面那条)
```

画面和 API 在同一个端口上。给别人看不用把整个浏览器交出去 ——
**分享链接默认只读**,而且只读是**服务端丢弃输入**,不是前端把按钮变灰:

```python
sess.share()                        # 默认只读,1 小时
sess.share(writable=True)           # 可操作 —— 能碰你所有登录态
```

## 浏览器从哪来

对"浏览器从哪来"只有一个要求:**一个 CDP 端点**。

| | 起什么 | 用在哪 |
| --- | --- | --- |
| `process`(默认) | `install` 下来的那个浏览器,一个进程 | 绝大多数时候 |
| `remote` | 什么都不起,CDP 端点你给 | 云浏览器、别人机器上那个、**你自己起在容器里的那个** |

这条线以上的代码**没有任何一处 `if runtime ==`** —— 为什么能做到,见
[works/07](docs/v2/works/07-runtime.md)。

**版本是钉死的**:每个 release 钉一个 Chrome for Testing 版本,升级前先跑
`tests/chrome_facts/`(「我们对 CDP 的假设逐条量过」)。

**下载源自动挑最快的** —— `install` 并发探候选源,量的是真实文件的吞吐,
不是 ping。要自己指定也行,**传进来的赢**:

```bash
WEBMUXD_BROWSER_MIRROR=https://cdn.npmmirror.com/binaries/chrome-for-testing webmuxd install
```

## 老实说,它没有什么

不藏着,免得你以为跑通了就都有了:

- **没有隔离。** 页面跑在你自己机器上。要隔离就**把 webmuxd 放进容器里**,
  或者用 `remote` 连一个别处的浏览器 —— 那是部署决定,不是我们的参数。
- **没有声音。** 画面是帧流,音频不在这条通道上。视频能放,但是静音的。
- **带宽不省。** 静止时是 0,动起来能到几 Mbps。xpra 那条靠 `scroll` 把滚动
  压得很低,但**全屏持续运动仍然贵**(实测 9 Mbps)—— 那是这条路线的性质:
  整屏都在动时,分区域重传会退化成整屏重传
  ([01 §4.1](docs/v2/works/01-frame-source.md#41-但更费带宽--更不流畅))。
- **没有桌面。** 文件管理器、系统对话框、非浏览器程序都没有。浏览器自己那些
  原生 UI(对话框、下载、文件选择、权限、Basic 认证)是**用 CDP 一条条收回来的**,
  见 [works/06](docs/v2/works/06-no-desktop.md)。

这几条不是"还没做",是**这条路线的性质** —— 画面是从浏览器的合成器直接出来的,
所以它只有页面,没有桌面,也没有声音。要完整桌面就该用远程桌面,不是用这个。

## 画面从哪来

默认走 **xpra**:它按 damage 区域编码,尤其是滚动 —— `scroll` 包**零字节搬像素**。
实测滚一页 Wikipedia,**57% 的重绘面积一个字节没花**
([works/12 §9](docs/v2/works/12-xpra-client.md))。

```bash
webmuxd install                                          # 有 root 就把它装上
webmuxd new --id work --port 7900                        # 默认就是 xpra
webmuxd new --id work --port 7900 --transport screencast # 零系统依赖那条
webmuxd info                                             # 这台机器上能不能走
```

要三个系统包(`webmuxd install` 会装,或者自己来):

```bash
apt install xpra xvfb python3-pil                     # Debian / Ubuntu
yum install xpra xorg-x11-server-Xvfb python3-pillow  # RHEL / CentOS / 阿里云
```

**装不上就报错,不会静默退回。** 静默退回等于让你以为自己在看 xpra 的画质;
退路是显式说一声 `--transport screencast`。

两条路的差别**只有像素从哪来**:输入、光标、tab、只读、原生 UI、日志、token
完全一样,观看页自己换成 canvas,别的代码一行不动。

什么时候该显式选 screencast:

- 机器上装不了 xpra(没 root、或者 macOS 没有 Xvfb)
- `--runtime remote` —— 那儿我们只有一个 CDP 端点,碰不到对面的 X 显示,
  **screencast 是唯一可能的画面来源**,也是那条路上的默认
- 要 `--dsf`(高 DPI 匹配)—— 它靠的是 screencast 那套参数
- **全屏持续放视频** —— 那是 xpra 的劣势区(实测能到 9 Mbps),
  整屏都在动的时候分区域重传会退化成整屏重传还多背分区开销

## 依赖

| | | |
| --- | --- | --- |
| **Python** | ≥ 3.10 | |
| **系统** | Linux / macOS | Chrome for Testing 没有 linux-arm64 构建,那种机器上用系统的浏览器 |
| **画面默认要的** | `xpra` · `Xvfb` · `PIL` | `webmuxd install` 会装。macOS 上没有 Xvfb,得显式 `--transport screencast` |

裸服务器上还要 chrome 的那些共享库和**中文字体**(没有字体的话中文全是豆腐块,
和代码无关)。这些连同 xpra 那三个,`webmuxd install` **有 root 就直接装**
(apt / dnf / yum 都认),没 root 就打出完整的那行命令。

## 开发

```bash
webmuxd install       # 测试用的就是它下的那个浏览器
pytest -q
```

测试跑的是**真的 Chromium**,不 mock —— 这个项目的全部价值就在它和浏览器的交界处,
换成假的等于什么都没测。用例[按场景组织](tests/README.md),不按代码模块:
`pointing_at_things/` 是"按字找东西",`pixels_on_a_wire/` 是"画面是我们自己产的",
`chrome_facts/` 是"我们对 CDP 的假设逐条量过"(换 Chromium 大版本先跑它)。

## 文档

| | |
| --- | --- |
| [QUICKSTART.md](QUICKSTART.md) | 完整跑一遍 |
| [`docs/v2/works`](docs/v2/works/) | **为什么这么做** —— 设计稿和实测记录 |
| [`docs/v1`](docs/v1/) | 存档。这个项目上一个形状(VNC 镜像那条路)的设计稿和规格 —— `docs/v2` 里那些"为什么翻转"的论证一直在引它 |

## 许可

Apache-2.0,见 [LICENSE](LICENSE)。

webmuxd 把 [Chromium](https://www.chromium.org/) 当外部程序驱动,**不改动、
不重新发行它** —— `webmuxd install` 是让你自己从 Google 的
[Chrome for Testing](https://developer.chrome.com/blog/chrome-for-testing) 下,
和 playwright / puppeteer 同一个姿态。
