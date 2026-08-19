# 更新日志

## 0.7.2

**⚠ 人在画面里操作时,密码框的明文会进日志。**

页面里那个输入探针报的是 `innerText || value` —— 而 `value` 在密码框上就是
明文密码。它会被写进 `log.jsonl`,`webmuxd log` 打得出来、`log/bundle`
打包带得走。

`log.py` 的注释一直写着"明文不该走到这儿 —— 凭证在执行层已经换成掩码了",
但**那条掩码只管 API 那条路**,人从画面进来的这条绕过去了。实测确认过。

改法:**控件的身份是它的标签,不是它的内容** ——
`aria-label` → `<label>` → `placeholder` → `name`/`id`,
表单控件(`input` / `textarea` / `select`)一律不取 `value`。

两条测试守着,其中一条不依赖跑浏览器所以永远会跑。

> 判据可以记成一句话:**记"他动了哪个控件",不记"控件里是什么"**。
> 后者要看,有 `observe` 和截图,那两条路上有明确的授权。

顺带新增 [works/13](docs/v2/works/13-agent-surface.md):给 agent 的操作面
和一条行为流,横向看了七家云浏览器。这个 bug 就是写那一篇时量出来的。

## 0.7.1

**xpra 那条路上 WebGL 是关的 —— 换默认的时候差点把它弄丢。**

有头的 Chrome 不像 headless 那样会自己退到 SwiftShader:Xvfb 上没有 GLX/DRI,
它直接把 WebGL 整个关掉(`SystemInfo.getInfo` 报 `webgl: disabled_off`)。
也就是说 0.7.0 把默认换成 xpra 之后,**WebGL 页面是白的**。

反直觉的一点:`--disable-gpu` **救不回来**,有头下它关得更彻底。
实测三种组合,只有 `--use-gl=angle --use-angle=swiftshader` 能把它救回来。

这个是写设计稿时量出来的,不是有人报的 —— 所以顺带补了
[works/11 §0](docs/v2/works/c-pixels.md):xpra / Xvfb / Xorg 各是什么、
四个虚拟显示选项怎么选、以及**要探哪些东西**(含两个还没探的缺口:
服务端的图像编码器、xpra 的协议版本)。

## 0.7.0

**画面默认走 xpra,依赖由 `webmuxd install` 装干净。**

### 默认翻了

```bash
webmuxd new --id work --port 7900                        # 现在是 xpra
webmuxd new --id work --port 7900 --transport screencast # 原来那条
```

0.6.x 的默认是 screencast,理由写的是"它零依赖"。**翻的理由不是偏好,是数**:
滚动时 xpra 的 `scroll` 包**零字节**干掉了 57% 的重绘面积,而 screencast
滚动是整屏重发([works/12 §9](docs/v2/works/12-xpra-client.md))。
**默认值该给的是好的那个,不是好装的那个** —— "好装"那一半交给 `install`。

**起不来就报错,不静默退回。** 静默退回等于让你以为自己在看 xpra 的画质:

```
✗ 默认走 xpra,但这台机器起不来:缺:Xvfb(Debian/Ubuntu:xvfb;RHEL:xorg-x11-server-Xvfb)
   装上:`webmuxd install`(有 root 就自动装,没 root 会打出该跑的那行);
   不想装就显式说:`--transport screencast`
```

`--runtime remote` 上不受影响:那儿只有一个 CDP 端点、碰不到对面的 X 显示,
**screencast 是唯一可能的画面来源**,所以它在那条路上就是默认,这不是降级。

### `webmuxd install` 现在真的把环境弄齐

**装是默认行为,不再要 `--with-deps`。** 探到缺了却不装,等于把活原样退回去 ——
`install` 的职责就是"跑之前把环境弄好"。**只有没 root 时才退化成打印**,
那时候我们确实做不了,而不是选择不做。

```
探测环境…
  python     3.11.2                                 ✓
  包管理     apt-get,可以装                         ✓
  浏览器     chrome 152.0.7977.42 已经下过          ✓
  共享库     齐                                     ✓
  中文字体   有                                     ✓
  xpra       齐                                     ✓
```

- **apt / dnf / yum 都认。** 原来只支持 Debian/Ubuntu。真机上撞了才知道
  这不是换个前缀:RHEL 那边 Xvfb 叫 `xorg-x11-server-Xvfb`、Pillow 叫
  `python3-pillow`,chrome 的共享库更是一个都对不上。
- **装不上要分清是"源里没这个包"还是"没权限"** —— 两者的下一步完全不同。
  xpra 在 RHEL 系不在基础源里,会直接告诉你去哪加源。
- **装完重新探一遍。** `apt-get` 返回 0 只说明命令没报错,不说明东西真的有了。
  判据永远是探测结果,不是安装器的退出码。
- `--with-deps` 还认,但会告诉你它已经是默认行为了。

### 别的

- `--dsf` 在 xpra 上用不了(尺寸由 X 显示定),报错里会说清 xpra 是你选的
  还是默认来的 —— 没说要 xpra 的人被告知"dsf 在 xpra 上没用",第一反应会是
  "我什么时候要 xpra 了"。
- `webmuxd install` 的输出按**显示宽度**对齐,中文标签不再把整块弄歪。

## 0.6.1

**xpra 在 RHEL 系的机器上起不来 —— 虚拟显示是发行版的打包方选的,不是我们。**

真机上(阿里云,xpra 6.5.2)第一次跑就挂在 `failed to locate Xorg binary to run`。
原因:xpra 用哪个虚拟显示写在它自己的 `/etc/xpra/conf.d/55_server_x11.conf` 里,
**Debian 那边默认 `Xvfb`,RHEL 那边默认 `xpra_Xdummy`(要整个 Xorg)**。

最难受的是它**绕过了我们的探测**:`which("Xvfb")` 明明探到了,xpra 转头去用
Xdummy,然后挂在完全另一个地方。**探的东西和用的东西必须是同一个。**

现在用 `--xvfb=Xvfb …` 显式指定,不看发行版配置。缺 Xvfb 时两个家族的包名都会说:

```
缺:Xvfb(Debian/Ubuntu:xvfb;RHEL/CentOS/Alibaba:xorg-x11-server-Xvfb)
```

另外那次报错的头一句是"xpra 起来了但浏览器的 CDP 没监听" —— 把人往浏览器的方向指,
而问题在 X 那一层。现在会先看 xpra 进程还在不在,分别说"xpra 自己退了 ——
多半是虚拟显示没起来"和"xpra 在跑,但浏览器的 CDP 没监听"。

## 0.6.0

**画面可以走 xpra 了。而且修了两个真 bug —— 其中一个让 0.5.5 / 0.5.6 的观看页
彻底不工作。**

### ⚠ 观看页从 0.5.5 起就是坏的

`index.html` 里整个 `<script>` 是**语法错**的:0.5.5 删一个分支时,
`} else if (m.type === "quality") {` 这一整行被写进了上一行注释里。

语法错意味着**一行都不执行** —— 没有画面、没有输入、没有 tab 条。
发了两个版本没人发现,因为**没有任何测试碰过那个文件**。

现在有两条挡着,一条不依赖任何外部工具所以永远会跑
(`tests/pixels_from_xpra/`)。

### ⚠ tab 被挤掉时,`evicted` 有时会丢

`await Target.closeTarget` 中间会让出控制权,而 Chromium 的 `targetDestroyed`
**经常比这个响应先到**。先到的话表已经被清干净了,后面那句
`self._order.remove(victim)` 抛 `ValueError`,于是 `reason="evicted"` 那条事件
**再也发不出去**。表现有两种:被挤掉的 tab 报成 `closed`,或者一个事件都没有。

这就是之前那条"偶发失败"的测试真正在说的事。现在谁先到都行,记账只做一次。

### 画面换 xpra

```bash
apt install xpra xvfb python3-pil
webmuxd new --id work --port 7900 --transport xpra
webmuxd info                       # 看这台机器上可不可用
```

**只有一件事变了:像素从哪来。** 输入、光标、tab、只读、原生 UI、日志、token
完全一样 —— 观看页自己换成 canvas,别的代码一行不动。

它强在按 damage 区域编码,尤其是 `scroll`:滚动时**零字节搬像素**。实测滚一页
Wikipedia,**57% 的重绘面积是 `scroll` 包干的,一个字节没花**
([works/12 §9](docs/v2/works/12-xpra-client.md))。

几条实测定下来的形状:

- **`start-desktop` 而不是 seamless。** seamless 下 `<select>` 下拉是一个独立的
  X 窗口,客户端得自己做窗口合成;desktop 下 X 把它合成进同一个窗口。
- **浏览器用 `--kiosk` 起,所以画面里没有 bar。** 不是"裁掉",是根本不画 ——
  连"鼠标 y 要加回 crop_top"那个坑一起不存在了。
- **输入不走 xpra。** 客户端只往那条连接发 6 种协议包,而代理那头还有一层
  **白名单**:`button-action` / `key-action` / `pointer-position` / 剪贴板 /
  文件传输全部丢弃。新出现的包类型**默认被拒**。
- **客户端是我们自己写的**,316 行(去掉注释)。因为 `xpra-html5` 里
  **没有解码器** —— 图像走 `createImageBitmap`,视频走 WebCodecs,
  那 5000 行是窗口管理、剪贴板、音频、jQuery,我们全都不要。

**默认仍然是 screencast**,因为它零依赖。要了 xpra 而机器上没有,
**报错并说清缺什么,不静默退回** —— 那等于让你以为自己在看 xpra 的画质。
`--dsf` 和 `--runtime remote` 在这条路上用不了,也是报错而不是悄悄忽略。

全屏持续运动反而是 xpra 的劣势区(实测能到 9 Mbps),那种场景 screencast 更合适。

一处细节:`--window-size=1024,768` 在 1024×768 的显示上实际只拿到 1023×767,
右下各露出一列纯黑。现在多要两格让它铺满 —— 代价是页面视口成了 1026×770,
右下各 2 像素在可见区域外([works/12 §10](docs/v2/works/12-xpra-client.md))。

## 0.5.6

**画质下限从 5 提到 25,`--dsf` 变成开关。**

### 下限:抄阈值的时候把下限也抄了,那一条抄错了

原来的降级路径是 `80 → 60 → 40 → 20 → 5`。**q5 是马赛克,根本没法用**,
而且 `20 → 5` 是个断崖。降质的意义是"糊一点但还能操作",不是"糊到看不清"。

25 不是拍的 —— BrowserBox 自己在 Tor 模式下就把下限压到 25
([works/01 §4](docs/v2/works/01-frame-source.md)),那是它认为的"还能用"的底。
现在是 `80 → 60 → 40 → 25`,**到底了改抽帧** —— 那才是链路真撑不住时该退的方向。

```bash
webmuxd new --id work --port 7900 --min-quality 40   # 想更保守就抬高它
```

下限高过上限会被夹住,否则它会在两头之间反复横跳。

### `--dsf`:默认关,而且光写 `--dsf` 就够了

它一直是默认关的(默认 `1.0`),但**得填数字**,而且 0.5.5 的文档里
`--dsf 2` 出现在示例第一行,看起来像推荐。两处都改了:

```bash
webmuxd new … --dsf        # = 2,Retina 那种最常见的情况
webmuxd new … --dsf 1.5    # Windows 150% 缩放
webmuxd new …              # 不给就是关
```

**只在状态栏显示"有效缩放 > 1.00x"时才开它。** 普通屏上开了,实测锐度反而
**低 18%**,还多花 2.6 倍带宽。

## 0.5.5

**清晰度那三个旋钮,以前一个都调不了。**

```bash
webmuxd new --id work --port 7900 --dsf 2 --quality 95 --format png
```

糊有**三个互不相干的来源,调错旋钮不会有任何效果**
([works/02 §4](docs/v2/works/02-frame-protocol.md))。页面底下那条状态栏就是
用来判断该调哪个的:

| 状态栏 | 说明 | 调哪个 |
| --- | --- | --- |
| **有效缩放 > 1.00x** | 屏是高 DPI,帧被**放大**了 —— 糊不是压缩造成的 | `--dsf 2`。**调画质完全没用** |
| **画质 掉到 60 / 40**,或带 `/2` | RTT 自适应在降质(阈值 725ms) | 链路问题,不是设置问题 |
| `1.00x` + `q80` 都正常 | 那才轮到编码 | `--quality` / `--format` |

**`--dsf` 不是"越大越清晰",它只用来匹配观看端的 dpr。** 普通屏上填 2,
实测锐度反而低 18%,还多花 2.6 倍带宽。

### 顺带修的三处

**① 状态栏的"有效缩放"算错了。** CDP 的 `screencastFrame` metadata 报的是
**CSS 尺寸** —— dsf=2 时它说 1024×768,而图其实是 2048×1536,拿它算出来的缩放
差一倍。而那一栏正是用来判断要不要调 dsf 的。现在以解码后的 `img.naturalWidth`
为准。

**② 降质现在留得下痕迹。** 以前只刷一下状态栏,而"什么时候降的、降之前 RTT
多少"是事后才会问的问题。现在进 scrollback,`webmuxd log` 查得到:

```jsonc
{"kind":"session","event":"quality_changed","quality":60,"rtt_ms":812,"direction":"down"}
```

**③ sessiond 自己的输出不再被扔掉。** 那行 `log.info("RTT 自适应:…")` 本来就
写了,但 stdout/stderr 是 `DEVNULL` —— 和 0.5.3 修的"chrome 的 stderr 被扔了"
是同一个错误犯了第二遍。现在落到 `<work>/sessiond.log`。

### RTT 自适应第一次端到端验证过了

`works/02 §3` 原来写着"想验证必须人为加延迟,否则它在测试里等于没跑过"。
**那句话不对**:把阈值搬到本机 RTT 之下、**死区照留**就行,实测跑出
`80 → 60 → 40 → 20` 的单调下降。

第一次试的时候我把 `SLOW_MS` 设成 0,死区被毁了,于是 down/up 来回震荡 ——
反过来证明了死区是干什么的:没有它,阈值附近抖动的链路会让画质一直变,
**比一直糊更难受**。

## 0.5.4

**绑址统一叫 `--bind`,默认只绑回环。**

之前三个参数,没一个能用:

| 现状 | 问题 |
| --- | --- |
| 全局 `-H/--host` | 是**连哪台机器**(客户端侧),不是绑哪个地址 |
| `webmuxd new` | **一个都没有** —— 想改绑址做不到 |
| `sessiond --host` | 默认 `0.0.0.0`,而且 `webmuxd new` 根本不传它 |
| `sessiond --host-only` | **死参数**,接了但从没接线,传了完全没用 |

`--host` 在这个 CLI 里已经占着"连哪台机器"的意思,再拿它表示"绑哪个地址"
必然打架。所以服务端那一侧**统一叫 `--bind`**(`sessiond` 那边旧名 `--host`
留作别名,免得 [works/07](docs/v2/works/07-runtime.md) 里那条命令突然报错)。

```bash
webmuxd new --id work --port 7900                  # 只绑 127.0.0.1
webmuxd new --id work --port 7900 --bind 0.0.0.0   # 对外,而且会警告
```

### 默认值这条在 v2 里比 v1 更要紧

| | v1 | v2 |
| --- | --- | --- |
| sessiond 默认绑 | `0.0.0.0` | **`127.0.0.1`** |
| 那个 `0.0.0.0` 是谁的 | **容器内的** —— 外面还有 `docker -p` 挡着 | **真的 0.0.0.0** |
| 那个口上有什么 | 纯 API | **画面口 —— 打开就能直接操作浏览器** |

v1 那个默认在当时是安全的(容器挡了一层)。v2 把容器删掉之后**前提没了,
而默认值忘了跟着改** —— 直到有人问"这默认绑 0.0.0.0 吗"才发现。

`webmuxd new` 走的那条路一直是绑回环的(实测确认过),所以**实际受影响的只有
直接跑 `python -m webmuxd.serve` 的人**。要对外是你的决定,但得显式说:

```
⚠ 画面口绑在 0.0.0.0 —— **这台机器网络能到的人,拿到 token 就能操作这个浏览器**
```

## 0.5.3

**root 下起不来,而且报错还不告诉你为什么。**

```
✗ runtime_unavailable: 浏览器起来了但 CDP 没监听
  手工跑一遍看报什么:/root/.cache/webmuxd/…/chrome --headless=new …
```

自己跑一遍才看到真正的原因:

```
ERROR:zygote_host_impl_linux.cc:102] Running as root without --no-sandbox
is not supported. See https://crbug.com/638180.
```

两处都改了。

### ① root 下自动 `--no-sandbox`,并且说出来

**这不是选择题** —— Chromium 在 root 下没有开着沙箱还能跑的配置。而且我们自己
推荐的隔离路子(把 webmuxd 装进容器,[works/07 §2](docs/v2/works/07-runtime.md))
默认就是 root:一律拒绝的话,我们推荐的做法自己走不通。

v1 的姿态是"默认不加 `--no-sandbox`",**这一条推翻了它** ——
但"不静默关掉安全特性"留着,它变成一条必须打印的警告:

```
⚠ 你是 root —— Chromium 在 root 下必须 --no-sandbox 才起得来(crbug 638180),
  已经替你加上了。**沙箱是关着的**;想要它就换个非 root 用户跑
```

### ② 起不来时,把浏览器自己那句话带出来

之前浏览器的 stderr 是 `DEVNULL` —— 于是只能让人"手工跑一遍看报什么",
**等于把排查工作原样退回去,而答案本来就在我们手里**。

现在 stderr 落到 `<work>/chrome.log`,失败时把最后几行塞进报错,
并且**去掉 Chromium 那一坨 `[pid:pid:时间:ERROR:文件:行]` 前缀** ——
它对使用者没有任何意义,留着只会把真正那句话挤出屏幕:

```
✗ runtime_unavailable: 浏览器起来了但 CDP 没监听:Running as root without
  --no-sandbox is not supported. See https://crbug.com/638180.
  完整日志在 /tmp/webmuxd-work-…/chrome.log
```

## 0.5.2

**修一个升级就撞的崩溃:登记表里的旧行会把第一条命令带崩。**

```
$ webmuxd new --id work --port 8090
  File ".../cli/registry.py", line 78, in list
    h = Handle(row["runtime"], row["id"], row["port"],
KeyError: 'port'
```

0.4 的 session 行是 `api_port` / `view_port`,0.5 只有一个 `port`
(当时的 works/04,已在重写中删除)。升上来之后 `~/.../sessions.json`
里还留着旧行,而代码里是裸下标 —— **第一条命令就崩,而且报错完全不指方向**。

规矩和环境记录那条一样:**格式对不上就当没有**。差别是这儿要**说出来** ——
那些 session 可能还真在跑,只是我们管不了了:

```
⚠ 登记表里有 2 行读不懂(多半是 0.4 留下的),已忽略:old2, work
  那些 session 要是还在跑,得自己清 —— 我们已经管不了它们了。
  登记表在 /run/user/0/webmuxd/default/sessions.json
```

警告只说一次,第一条成功的命令会把表重写干净。

### 另外两个 bug,是拆 playwright 的 install 时照出来的

写 works/10(当时的 works/10,已并进 d)(把 playwright 的安装机制逐条拆开)
的时候对着自己的代码核,发现两处:

- **解压到一半会看起来像装好了。** 实测:目录里只放一个已 chmod 的 `chrome`、
  别的全缺,`find()` 照样返回路径 —— 然后我们去跑一个残缺的浏览器。
  抄 playwright 的 `INSTALLATION_COMPLETE`:标记是解压和 chmod **之后**才写的
  最后一步。
- **下载失败时只删了 `.part`**,解压出来的半个目录留着。现在一起删。

**迁移代价**:0.5.1 及更早装的浏览器没有标记文件,升级后会重下一次。
150 MB 不能静默发生,所以 `install` 会先说一句「装了一半或是旧版本装的,
重下一次」再动手。

## 0.5.1

**`webmuxd install` 自己挑最快的下载源。**

```console
  下载源        探测中…
     官方               1.8 MB/s     ✓
     npmmirror        0.4 MB/s
     npmmirror cdn    0.3 MB/s
```

三条讲究:

- **探的是真实那个文件的头 256 KB**,不是首页也不是 ping —— 首页快不代表大文件快,
  CDN 的回源路径经常不一样
- **量吞吐,不量 RTT** —— 要下的是 150 MB,握手快 20ms 一文不值
- **传进来的赢**:显式给了 `--mirror` 或 `WEBMUXD_BROWSER_MIRROR` 就不探了。
  探测是"这台机器上哪个快"的**事实**,你指定哪个是你的**选择**

全都探不通就退回官方,**让真正的下载去报错** —— 那儿的原因(DNS 不通 / 403 /
超时)比一句"探测失败"有用。

### 顺手修的两处

- **下载失败的原因不再截断。** 之前截到 30 字符,截在半句上
  (`<urlopen error [Errno -2] Name`)—— 而原因决定了下一步该做什么。
- **版本号只剩一处。** 0.5.0 发版时两处各写一份,只改了 `pyproject.toml`,
  装出来的包 `webmuxd info` 报的是上一版的号,**只有在干净 venv 里装完才看得出来**。
  现在 `pyproject.toml` 用 `dynamic` 从 `webmuxd/__init__.py` 读。

### 为什么没有阿里云那个源

`https://mirrors.aliyun.com/google-chrome/` 看着正是我们要的,**但它不是**:
托管的是 Google Chrome 稳定版 / beta 的 `.deb` / `.rpm` **系统包**,不是
Chrome for Testing 的 zip;而且只有 `current`,历史版本停在 112 那一带 ——
**没有版本可钉**。

拿它当源等于把「每个 release 钉一个版本、升级前先跑 `chrome_facts`」整个作废,
而那是选 Chrome for Testing 的**唯一理由**([works/07 §4.1](docs/v2/works/07-runtime.md))。

真想用系统装的 Chrome,那是另一条路:`--browser /usr/bin/google-chrome` ——
显式、看得见、不假装自己是钉死的那一版。

## 0.5.0

**画面自己产。** VNC、桌面、docker 整条路砍掉 —— 一个端口,人打开就能看,
代码打同一个口。设计稿在 [`docs/v2/works`](docs/v2/works/)。

```bash
pip install webmuxd
webmuxd install                     # 下一个钉死版本的浏览器,不要 docker
webmuxd new --id work --port 7900   # 一个口
```

### 变了什么

| | 0.4 | 0.5 |
| --- | --- | --- |
| 画面从哪来 | 镜像里的 KasmVNC / TigerVNC | **CDP 的 `Page.startScreencast`,我们自己产** |
| 人的输入 | VNC 协议,我们不参与 | **CDP `Input.*`,我们翻译** |
| 对外几个口 | 两个(`--api-port` + `--view-port`) | **一个(`--port`)** |
| 浏览器从哪来 | 4.4 GB 的桌面镜像 | **`webmuxd install` 下一个**,钉死版本 |
| 要不要 docker | 要 | **不要**。项目里再没有一个 Dockerfile |
| 一台机器几个 | kasmweb 只能一个 | **想几个几个** |
| 画面里有什么 | 整个桌面,得裁掉 tab 条 | **只有页面内容** |

**破坏性改动**,旧名不会被静默吞掉,会直说:

- `api_port=` / `view_port=` → **`port=`**;CLI 的 `--view-port` 退役
- `image=` / `--image`、`network=`、`runtime="container"` → **删**。要隔离就把
  webmuxd 放进容器里跑,那是你的部署决定,不是我们的参数
- `view_login` / `view_password` → **删**,换成 token
- `~/.webmuxd.json` 格式 1 → 2(老记录读不动就当没有,重新探)

### 新增

- **`webmuxd/view/`** —— 28 字节帧头、ack 背压、RTT 自适应降质、输入翻译
  (含 IME 和粘贴)、光标同步、一个内置观看页面
- **`webmuxd/native/`** —— headless 里不渲染的六类原生 UI 用 CDP 收回来:
  JS 对话框、下载、文件选择、权限、Basic 认证、PDF。**不替你决定、有超时、
  超时写日志**
- **`webmuxd/browser.py`** —— Chrome for Testing 下载器,每个 release 钉一个版本;
  `WEBMUXD_BROWSER_MIRROR` 换源(国内用 npmmirror)
- **只读分享第一次是真的** —— 只读是**服务端丢弃输入**,不是前端把按钮变灰

### 一个字没动的

定位、观测、日志、tab 表、错误模型、`act()` 不抛异常 —— 它们和画面从哪来无关,
所以 `core/` 一行没改。详见 works/08(当时的 works/08,已删)。

### 老实说,它没有什么

- **没有隔离**,页面跑在你自己机器上。要隔离:把 webmuxd 装进容器,
  或者 `runtime="remote"` 连一个别处的浏览器
- **没有声音**。视频能放,但是静音的
- **带宽不省**,滚动时能到 10 Mbps(静止是 0)。但实测流畅度**反而比 VNC 好** ——
  全屏运动正是区域重传的负收益区
- **没有桌面**。要完整桌面就该用远程桌面,不是用这个

## 0.4.4

**收掉 0.4.3 露出来的一道缝:登记表丢了,东西还在,却没人管得了。**

`webmuxd new` 遇到一行死 session 时会先把它从登记表里删掉,再去起。要是这一起
没成(比如 `--view-port` 和还跑着的容器对不上),**容器还在、登记表里却没它了** ——
`webmuxd kill -t work` 只会说"没有这个 session",而 0.4.3 那条错误提示恰好就是
让人去 kill。

两处都改了:

- **死行留到起成功为止**。成功了 `put` 会覆盖它;没成功,留着的这行正是 kill
  找得到东西去清的依据。
- **`kill` 在登记表里找不到时,再按容器名认一次**。`webmuxd-<id>` 这个名字只
  可能是我们自己留下的,所以有资格认领 —— 否则人只能自己去敲 `docker rm`。

## 0.4.3
## 0.4.3

**同一个 id 再来一次不该失败。**

上一次起到一半失败,容器停在那儿没清掉,名字就一直占着:

```
✗ runtime_unavailable: docker run 失败:… The container name "/webmuxd-work"
  is already in use by container "c9cda52…"
    先手工 docker run 一次看看
```

**报错指向 docker,而真正该做的事一个字都没提。** 现在只有一条规则:

| 名字上那个容器 | 怎么办 |
| --- | --- |
| **停着的** | 删掉重来 —— 那是上次失败留下的尸体,里面没有任何值得留的东西 |
| **还跑着的** | 接回来,**不重建** —— 同一个 id 就是同一个浏览器,这才叫幂等 |

接回来的那条路会把 sessiond 重新挂到活着的容器上,**页面、登录态、口令都还在**
(口令是从容器里读回来的,不是重新生成一个)。重建等于把人正开着的东西全丢掉。

两件事不猜:读不出 CDP 口就报错(猜错的话 sessiond 会连上另一个浏览器,而一切
看起来都正常);`--view-port` 和容器实际的口对不上也报错(容器的口是启动那刻定的,
改不了 —— 默默沿用旧口的话,你会拿着给的那个去连一个空端口)。

### `alive()` 以前只问了 docker

容器活着**不等于**这个 session 能用。sessiond 掉了、容器没掉的时候,老的 `alive()`
照样报 ready,于是 `webmuxd new` 说一句"已经在跑了"然后什么都不做 —— 而 `api_url`
是死的。`ready` 承诺的是"你现在就能用它",所以现在两个都问。

这也是上面那条"接回来"能被触发的前提。

## 0.4.2

**修:云主机上 `--network host` 起不来**(阿里云是典型)。

那类机器的 `/etc/hosts` 里没有自己 hostname 的 IPv4 记录。host 网络下容器沿用
这份 hosts,于是 kasm 的启动脚本连环失败:

```
hostname -i           → Name or service not known      (set -e + ERR trap)
cleanup() 里 kill $!  → $! 是空的 → kill: usage: …
                      → 容器 Exited (2)
```

**两处都修了,而且都不用动你的宿主机:**

1. 镜像里把 `$(hostname -i)` 改成解析不了就退回 `127.0.0.1` ——
   那两个值**只用来打日志**(一处 DEBUG 时 echo,一处写进 log),
   没有任何东西绑它。整个容器为一个谁都不用的变量死掉。
2. host 模式下 `docker run` 加 `--add-host <宿主机 hostname>:127.0.0.1` ——
   `xauth` 拿 hostname 拼显示名(`<主机名>:1`),这一步光靠上面那条救不了。

**不改宿主机的 `/etc/hosts`**:那是为了迁就容器去动系统文件,而且换台机器
还得再来一次;报错又是 `kill: usage:`,和 hostname 一点关系看不出来。

### 顺带查清一桩悬案

用 kasm 自带的 `KASM_DEBUG=1`(会开 `set -x`)看到真实展开:

```
vncserver :1 … -geometry 1280x720 … -interface 0.0.0.0 …
```

**命令行上 `-geometry` 有值,而 Xvnc 最终仍用它自己的 1024x768** ——
这个 KasmVNC 版本的 `vncserver` 根本没吃命令行上的这些选项。
所以"kasm 桌面分辨率改不了"是上游的事,不是我们没接上;
那个能力继续不声明。

## 0.4.1

**本机没有镜像时自己拉,不再叫你去 `docker pull`。**

`docker run` 本来就会自动拉。是 0.2.0 加"读镜像标签"时先做了一步
`docker inspect`(它只看本地),才把这条路挡成:

```
✗ runtime_unavailable: 本机没有镜像 …
  先 docker pull,或者按 docker/README.md build 一个 wrapper
```

**那是自己制造的障碍,不是真的要求。** 现在 inspect 落空就先 `docker pull`
再读一次;拉之前会说一声(底座 4 GB,静默几分钟比报错还难受),拉不到则
把 registry 的原话带出来 —— 名字打错和网络不通是两回事,提示要分得开。

## 0.4.0

**全是改名。一件事一个词,三层贯通。**

之前同一个概念在三层各叫各的 —— 最糟的是"看画面的口令":CLI 上根本没有参数
(只能设 `WEBMUXD_TOKEN`)、lib 叫 `token=`、镜像叫 `WEBMUXD_PASSWORD`。
而"给人看的那个口"叫 `--vnc-port`,把**实现名**写进了契约:三个镜像里
kasm 是 KasmVNC、jlesage 是 TigerVNC、Selkies 干脆不是 VNC。

规则:**CLI `--连字符` / lib `下划线=` / 镜像 `WEBMUXD_大写`,同一个词。**

| 概念 | CLI | lib | 镜像 env |
| --- | --- | --- | --- |
| 人看的口 | `--view-port` | `view_port=` | `WEBMUXD_VIEW_PORT` |
| CDP 口 | `--cdp-port` | `cdp_port=` | `WEBMUXD_CDP_PORT` |
| webmuxd 自己的口 | `--api-port` | `api_port=` | — |
| 画面尺寸 | `--window-size` | `window_size=` | `WEBMUXD_WINDOW_SIZE` |
| 口令 | `--password` | `password=` | `WEBMUXD_PASSWORD` |
| 登录名 | `--login` | `login=` | `WEBMUXD_LOGIN` |
| 鉴权 / TLS | `--auth` / `--tls`(可 `--no-`) | `auth=` / `tls=` | `WEBMUXD_AUTH` / `WEBMUXD_TLS` |
| 绑定地址 | `--bind` | `bind=` | `WEBMUXD_BIND` |

镜像标签同步成 `webmuxd.<域>.<字段>`:`view.*` / `cdp.*` / `chromium.*` /
`host.network` / `tz.env` / `window_size.env`。

### 还顺手补上的

- **`--cdp-port` 现在可以指定**(以前只能自动挑)。不给仍然自动 —— 它只在本机用。
- **`--password` / `--login` 之前在 CLI 上根本不存在**,只能靠环境变量。
- `-p` 以前在 `new` 里是 `--port`、在别的子命令里是 `--print-only`,**同一个短选项两个意思**。现在长名是唯一正式写法。

### 破坏性变更

`--vnc-port` → `--view-port`,`-p/--port` → `--api-port`,`-v/--viewport` →
`--window-size`(旧写法仍作别名保留一版);

**lib 的旧名不再工作**,而且**不会静默吞掉** —— `port=` / `vnc_port=` /
`viewport=` / `token=` 会直接报错并告诉你新名字。以前它们会落进 `**kw` 被丢掉,
然后报一个指向别处的错。

`Session.vnc_url` / `vnc_user` / `vnc_password` → `view_url` / `view_login` /
`view_password`;`Handle.vnc_port` → `view_port`。

## 0.3.1

修 0.3.0 里"观测带上分辨率"那个功能 —— **它是坏的发出去的**。

`_page_info` 从页面拿到的是扁平的 `w/h/screenW/screenH`,但它会**重排成嵌套结构**
(`viewport` / `scroll`)。我两头都按扁平写:服务端重排时把 `screen*` 丢了,
客户端又按扁平去读,于是 `obs.viewport` / `obs.screen` 永远是 `(0, 0)`。

单元测试当时是绿的 —— 因为它测的是我自己写的形状,不是 API 真正发出来的那个。
所以补了一条**照抄真实响应形状**的回归测试。

## 0.3.0

### 镜像开关统一

两个镜像现在吃同一套变量,`docker run` 的人不用记哪个底座叫什么名字
(wrapper 的 entrypoint 负责翻译):

| | |
| --- | --- |
| `WEBMUXD_WINDOW_PORT` / `WEBMUXD_CDP_PORT` | 两个端点各听哪个口 |
| `WEBMUXD_BIND` | 窗绑哪个地址 —— `127.0.0.1` 只在本机,`0.0.0.0` 对外 |
| `WEBMUXD_PASSWORD` / `WEBMUXD_USER` | 看画面的口令 |
| `WEBMUXD_AUTH` | 要不要口令 |
| `WEBMUXD_TLS` | https 还是 http |
| `TZ` | 时区 |

对应到库和 CLI:`bind=` / `auth=` / `tls=` / `tz=`,以及
`--bind` / `--no-auth` / `--no-tls` / `--tz`。

**能力不是每个镜像都有,没有就报错、不装作可以。** 例如 KasmVNC 的画面口恒 TLS
(实测拿掉 `-sslOnly` 也一样),所以要 http 会直接报错 —— 装作可以的话,
调用方会按 `http` 去拼一个连不上的 URL。

### 观测带上分辨率

`observe()` 现在给两个尺寸:`viewport`(**元素坐标活在这个尺寸里**)和
`screen`(桌面)。`as_prompt()` 在两者不同时显示。

**为什么要带**:Xvnc 开着 `-AcceptSetDesktopSize`,也就是**观看者打开页面时
可以改掉桌面分辨率**。分辨率一变响应式站点会重排,上一次观测的坐标就作废了。
带出来,调用方才能发现"地动了",而不是纳闷为什么点偏了。

### 默认分辨率

- 默认改成 **1024x768**,跟默认镜像(kasm)固定的桌面尺寸对齐 ——
  以前窗口 1280x800、桌面 1024x768,边上是被裁掉的
- 默认值本身可配:`WEBMUXD_VIEWPORT`

### 已知没做到

- **kasm 的桌面分辨率改不了**,所以那个镜像不声明这个能力
  (见 `docker/kasmweb-chromium/README.md` 里排除过的几种可能)。
  要自定义分辨率用 `jlesage-chromium`

## 0.2.0

**这一版重写了容器那一半。** 0.1.x 把一个镜像的细节写死在代码里,现在改成
镜像自己声明、runtime 照着读 —— 加一个新镜像不用改 webmuxd。

### 镜像

- **两个现成的镜像**,在 kasm / jlesage 原厂镜像上加一薄层,补上 CDP 端点:

  ```
  ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0          画面最好
  ghcr.io/memory-co/webmuxd/jlesage-chromium:v26.08.1        能一机多开
  ```

  国内从 `docker.cnb.cool/agentuse/webmuxd/` 拉,同一个 digest。

- **端口用统一的变量名**:`WEBMUXD_WINDOW_PORT` / `WEBMUXD_CDP_PORT`,
  两个镜像一样,wrapper 翻译成各自底座认的名字。
- **profile 写在镜像标签里**(`webmuxd.*`)。webmuxd 靠 `docker inspect` 认镜像,
  **不认名字** —— 所以 `--image` 指任何打了标签的镜像都能用。
  没有标签就直接报错,不猜。

### runtime

- `container` 默认走 **`--network host`**:容器里的 `localhost` 就是你的 ——
  调试本机跑着的页面用得上。`network="bridge"` 仍然可用,换来网络隔离。
- **默认镜像**改成 `ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0`。
- 不再 `docker exec` 往容器里挂中继 —— CDP 由镜像自己送出来。

### install

- `webmuxd install` 只回答两个问题:**docker 能用吗、镜像拉不拉得到**。
  不 build、不预拉(用 `docker manifest inspect` 问一下,不下 4 GB)。
- `~/.webmuxd.json` 变成扁平的事实记录:**键在 = 探到了,键不在 = 没探到**。
  拉不到镜像就不写 `default_container`,让你用 `--image` 自己指。

### 砍掉的

- **`--forward`**(把宿主机端口映射进容器)—— host 网络下不需要;
  它原本要么预先列端口、要么按需挂 + 失败重试,是一整套没必要的机制。
- `--bind` 只在 `--network bridge` 下有效(host 下没有 `-p` 能管它)。

### 文档与测试

- 测试改成[按场景组织](tests/README.md),13 个场景各有 README 说明
  **测什么 / 不测什么**;两个镜像各有一个真跑 `docker run` 的场景。
- 新增 [works/08](docs/v1/works/08-browser-runtime.md):浏览器 runtime 的契约
  只有两个端点,以及新镜像怎么进来。
- 这一族的规范搬到了
  [shellbase](https://github.com/memory-co/shellbase):`new-interface` / `muxd-spec`。

### 破坏性变更

- `ContainerRuntime.start()` 不再接受 `forward=`;`bind=` 只在 bridge 下生效。
- 默认镜像换了 —— 0.1.x 的 `kasmweb/chromium:1.18.0` 没有 webmuxd 标签,
  现在会被拒绝并提示去 build 或 pull 带标签的那个。
- `~/.webmuxd.json` 的格式变了。老记录读不动就当没有,重新 `webmuxd install` 即可。

## 0.1.1

- `webmuxd install` / `~/.webmuxd.json`:探一次环境记下来,之后的命令不再重复探。
- `container` runtime 跑 `kasmweb/chromium`,CDP 经容器内一跳中继送出来。

## 0.1.0

第一个版本。三个对象(`Webmuxd` / `Session` / `Tab`)、按可见文字定位、
观测层(元素表 + 标注截图)、操作日志、三种 runtime、CLI。
