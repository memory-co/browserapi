# 更新日志

## 未发布

### 新增 `webmuxjs/extension/` —— 和 sidecar 平级

装进被控浏览器的一个 MV3 扩展。分工的判据只有一条:**这件事要不要碰页面。**

| | 跑在哪 | 干什么 |
| --- | --- | --- |
| `sidecar` | **被控页面里** | 改/看页面本身:光标、人在动没在动 |
| `extension` | **浏览器自己那一层** | 浏览器替我们做的:窗口、tab |

不用碰页面的一律往这边搬 —— **每搬一样,"探针改变了页面环境"那条代价就小一分**。

今天搬了一样:**popup 一律变成 tab**。做法是等 Chromium 把那个窗口开出来,
再 `chrome.tabs.move` 搬回主窗口,**一个字都不注进页面**。
三处比 sidecar 里那个 `open-shim` 强(实测,Chromium 152):

| 页面调的 | `open-shim` | 扩展 |
| --- | --- | --- |
| `width=400,height=300,left=10` | tab | tab |
| `popup=1` | tab | tab |
| `noopener,width=400` | tab,返回 `null` | tab,返回 `null` |
| **`attributionsrc`** | **POPUP** ⚠ | **tab** |

1. **不碰页面** —— 没有 `window.open` 补丁、没有伪造 `toString`
2. **不需要白名单,所以没有那个洞** —— 白名单必然有"少列了一个词"的失败,
   而它真的漏过:`attributionsrc` 在 `KEEP` 里留着,实测**照样开出真窗口**
   (代码注释写的"它们不触发 popup"是错的)
3. **`noopener` 的 `null` 自动保住** —— 那是 Chromium 自己算的,我们没插手

**权限面比 sidecar 小得多**:只有 `"permissions": ["tabs"]`,
**没有 `host_permissions`、没有内容脚本**,有测试盯着这三样。

**sidecar 那个 `open-shim` 先留着,已标注要被替代。** 两套并存是安全的,
而且比任何一边单独都严:shim 先把 features 过滤掉,于是根本不开 popup,
扩展那条就成了空操作;唯一两边不一致的 `attributionsrc`,扩展接得住。
**等下一版发出去、验完功能完全等同,再删 shim。**

一条真代价:那个 popup 窗口**真的被创建了**再被搬走。无头下看不出来;
**有头(VNC)那条腿上它可能闪一下** —— 这条**还没在有头下实测过**,
文档里标了。

`remote` 那条路装不了扩展 —— 那个场景不做,见
[works/l](docs/v2/works/l-extension.md)。

新增 [`tests/the_extension/`](tests/the_extension/)。

### 改名:`MachineFacts` → `HostEnvs`

连同它那三个子项和那个版本常量一起,**否则容器和内容会是两个词**:

```
MachineFacts   → HostEnvs        BrowserFact → BrowserEnv
FACTS_VERSION  → HOSTENV_VERSION XpraFact    → XpraEnv
                                 RrwebFact   → RrwebEnv
```

**磁盘上那份 `~/.webmuxd.json` 一个字节都没变** —— 类名不出现在 JSON 里,
键还是 `default_browser` / `xpra` / `rrweb` / `xvfb` / `version`,
所以老记录照样读得回来,`HOSTENV_VERSION` 也不用动(还是 3)。

它在 `models.__all__` 和 `docs/v2/sdk/README.md` 那张表里,**算公开面**。

## 0.18.0

**画面上是新闻页,tab 条和地址栏却指着首页。** 用户报的,附了截图和日志。

### 根:`active` 是那张表里唯一一本"我们自己记的账"

tab 表里的每一样都来自浏览器自己的 target 表 —— 开、关、url、title,
全是 CDP 推过来的。只有 `active` 不是:我们记一个字段,再用
`Target.activateTarget` 把浏览器拽过来对齐。

那本账有一个没写出来的前提:**只有我们会动前台。**

不是的。页面 `window.open` / `<a target=_blank>` 开出来的 tab,
**Chromium 直接把前台切过去,而且不发任何事件**(实测:新那个
`visibilityState=visible`,原来那个 `hidden`,而我们那张表纹丝不动)。

两条腿各错各的,**都不报错**:

- **VNC**:画面是那个真窗口,人看到的是新那一页,tab 条、地址栏、
  不带下标的命令全指着旧那一页。**输入也打在旧那一页上** ——
  人看着新闻页,点下去落在一个看不见的页面里。
- **JPG**:截屏还挂在旧 target 上,后台不产帧,画面**冻在最后一帧**。
  看着一致,其实已经死了。

设计稿里那句「漂移在物理上不可能:真漂了就是黑屏,立刻可见」**是错的**,
已改。它错在把"没有新帧"当成了"没有画面"。

### 改法:让浏览器说了算,一个例外都没有

> **`active` 就是"浏览器现在把哪一页放在前台"。
> 我们的命令只是发个信号,要等那一页自己报回来才算数。**

理由不是省事,是**浏览器判得比我们好**。同一个 `target=_blank` 链接:
**普通左键前台开,Ctrl+左键和中键后台开** —— 而我们那条输入腿本来就把
`modifiers` 和 `button` 原样转给了 CDP。人的意图靠手势表达,Chromium 解释它。
我们自己再定一套"跟不跟",第一件事就是把 Ctrl+左键判错。

于是「没有第二份账本」这句话第一次真的成立。

三件配套的:

- **每个 tab 一进表就装探针**(原来是懒的)。没装探针的那一页是**哑的** ——
  实测页面开出来的 tab 在被人碰之前 `window.__wm_side` 是 `undefined`,
  而那恰恰是最常见的那种前台变化。顺带补掉两个本来就缺的:
  那个 tab 里的光标同步、人的操作流水。
- **`select-tab` / `new-tab` 阻塞到确认为止。** 返回即为真。
- **等不到不静默成功**:超时后主动问一次 `document.visibilityState`
  (仍是观测,不是猜),还问不到就报错。

### 行为变更(两条,都在明处)

**`resolve_tab(None)` 的语义变了** —— 从「我们表里记的那一页」变成
**「屏幕上那一页」**。人点了个 `target=_blank`,前台跟着换,不带下标的
下一条命令也跟着换。**要确定性就带下标**(`-t nt:0`)。

**广告能搭 agent 那次点击的顺风车** —— Chrome 拦掉没有手势的 `window.open`,
但 agent 的 click 就是一次手势。缓解同上,而且这件事现在**看得见**:
tab 条会跳、流水里有 `tab.activated`。

### `webmuxjs/sidecar/` —— 注进页面里的那一段,单独成一棵

原来是四段 Python 字符串字面量,散在 `probe.py` / `cursor.py` 里,
各自把 `addBinding` + `addScriptToEvaluateOnNewDocument` + `evaluate`
那套仪式走一遍。两个问题,后一个更要命:

1. 四份一样的仪式,就是四次犯同一个错的机会 —— 而那个错犯过两次
2. **那是全项目唯一一块没有类型检查、没有单元测试的代码,
   而它跑在别人的页面里**。密码明文进日志那次就是从那儿漏出去的

现在和观看页平级、同一套工具链:`tsc` 管类型、`vitest` 管行为、
`vite` 打成一段不留全局的 IIFE(4.4 KB)。一次注入、一个 binding。
里面四样:popup 转 tab、人在动没在动、光标形状、**这一页是不是前台**。

`webmuxd/probe.py` 没了;`cursor.py` 只剩那份白名单(它是信任边界,
必须留在服务端)。两条跨语言接缝各有测试盯着:binding 名两边一致、
探针不读表单 `value`(而且读的是**建出来那份**)。

### 为什么这个 bug 在测试里全绿地跑了很久

`v2_browser_new_tab` 用 Playwright 开真浏览器、连光标都验了,照样没抓到。
三件事叠在一起:

1. **四条断言,一份账。** bar 高亮、地址栏、后端 `active`、不带下标的命令 ——
   看着像交叉验证,其实全是同一张表的四种呈现。**一份账抄四遍,
   再怎么对账也对不出问题。**
2. **画面只被问过"变没变",从没被问过"你放的是哪一页"。**
3. **跑的是 JPG,而这个 bug 在 JPG 下是隐形的**(画面冻住,前两条判据全过)。
   用户遇到的是 VNC,而那一段从来没在 VNC 上跑过。

对应补了三样:判据换**来源**(页面的 `visibilityState`)、判据换**问题**
(小站每页一个底色,于是"画面上是哪一页"答得出来)、
**同一段在 VNC 腿上再跑一遍** —— 一条腿绿不能替另一条说话。

新增 [`tests/who_is_in_front/`](tests/who_is_in_front/);
`v2_browser_new_tab` 多一条 VNC 用例,**同一个链接三种点法**各验一遍。

## 0.17.0

**两个"看起来什么都没发生"的 bug**,都是被测试里的固定睡眠盖住的。

### ① 人正在打字,地址栏被抹掉

那串地址属于 **tab**,却存在一个共享的输入框里,而每次重画都无条件
`$("url").value = t.url` —— 于是**人打了一半的地址,会被后台任何一个 tab
的标题变化、加载完成冲掉**。冲掉之后回车发出去的是别的东西,而且一声不吭。

两条规矩:**人在框里就一个字都不动它**;**每个 tab 记着自己那份草稿**,
切走再切回来,打了一半的字还在。

(没做成"每个 tab 一个框":真浏览器也是一个地址栏,全屏之后屏上更放不下
N 个。**问题从来不在有几个框,在于那份状态被存错了地方。**)

### ② 人自己的动作,被"人正在操作"挡住了

`busy_human` 说的是"人正在操作,别去抢方向盘" —— 那是对**别人**说的。
而观看页上的地址栏、前进后退,发起者**就是人自己**:拿"人正在操作"
去挡人自己的下一下,是自相矛盾。

撞到的样子:人在画面里敲完字,顺手在地址栏回车 —— 服务端回 409,
客户端只弹个 toast,**看起来什么都没发生**。

现在观看页如实报自己是 `human`,服务端认这条语义。附带一个好处:
**行为日志里这些动作记成 `human` 而不是 `api`** —— 那本来就是真的。

### 测试:固定等待换成真判据

kit 里一排 `wait_for_timeout(1200/1500/2000/3000)` 全部换掉:
`click` 等日志里那条 `pointerdown`(服务端真收到了)、`type` 等 N 条 `keydown`、
`go` 等 tab 条上真的变成那个地址、`new_tab` 等新那个成为当前、
`resize` 等帧尺寸追上、`switch_to` 等**新那条腿成了当值的那个**。

日志走 `/api/log` 那条 HTTP —— **和 CLI、和观看页上那个日志按钮同一个接口**。

上面那两个 bug 和第三个(`switch_to` 一直在拿上一条腿的画面当"换好了")
都是这么翻出来的:**睡够了就撞不上,所以从来没人发现**。
这比慢严重得多 —— 固定等待最坏的地方不是慢,是让真问题看不见。

顺带快了:`v2_browser_new_tab` 35.3s → 25.3s,`v2_browser_modes` 21.8s → 13.2s,
`v2_browser_simple_dom` 11.3s → 6.4s。



**DOM 那条腿会把一个核烧满,而且拖垮整个 server。** 这一版修四件事,
其中三件**不报错**。

### ① 事件缓冲是 O(n²)

页面每来一条 rrweb 事件都要 `_trim` 一次,而 `_trim` 为了"必须从全量快照砍起"
会把后半段(三千多条)**逐条 `json.loads`** 找切割点。一个**开着不动**的页面
(唯一那张快照在下标 0,之后全是增量)**永远找不到** —— 于是缓冲一路涨,
每条新事件重新解析一遍,越涨越慢。

实测:正常 100 条 1.2ms,退化之后 **510ms —— 慢 408 倍**;缓冲
6701 → 7201 → 7701 一条都砍不掉。单核打满,整个 server 的事件循环被堵死,
连 `/healthz` 都答不上(于是 `server stop` 报"没有在跑的 server",见 ③)。

**换个想法**:切割点是**造**出来的,不是**找**出来的。让页面定期重出一张
全量快照(rrweb 内置的 `checkoutEveryNth`),Meta 一到,"从这里重来"那条
分支自己就把缓冲清了。`_trim` 整个删掉。另加一条硬上限兜底 ——
快照要是不来就丢掉重来**并吵一声**。

### ② 后台 tab 的变化混进当前 tab 的增量链

整个 session 共用**一条**链(`_on_binding` 把 sid 忽略了),而每个 tab 都在录。
于是后台那个的 mutation 会混进当前这条链,客户端拿它们去改当前那棵树 ——
**改出来的是一棵没人见过的树,而且不报错**。
实测:当前页一动不动,6 秒里混进来 6 条。

现在**只有当前那个 tab 在录**。切过去时重开一次 —— rrweb 一开始录就先出
一张全新的全量快照,那正好是"从快照往下"。

### ③ 没人看的时候,所有 tab 都在录

`active` 变了要不要跟,原来挂着"有人在看才跟"的条件。而"跟"这件事里除了
搬画面,还有"只让当前那个 tab 录 DOM" —— 那跟有没有人看**没关系**。
加了那个条件的下场是:**没人看的时候所有 tab 都在录,而且混着**,
而"没人看"恰恰是最该停录的时候。

### ④ `server stop` 停不掉一个忙住的 server

它判断"有没有 server"用的不是"有没有进程",而是"两秒内 `/healthz` 答不答"。
一个被 ① 打满 CPU 的 server 就是答不上 —— 于是它被判定为**不存在**,
**退出码还是 0**,而且没有任何一条命令停得掉它。

现在答不上话时**再看一眼进程**:记录里存着 pid,还活着就按进程组停掉
(连它底下的 chrome、xpra、虚拟显示一起 —— 只杀它自己的话那些全成孤儿)。

### 另外:一个漏出去的调试开关

`-d screen,randr` 是查像素对齐时临时加的,跟着 0.13.0 / 0.14.0 / 0.15.0
一起发了出去 —— 每个 VNC session 的 xpra 都在写 screen/randr 的调试日志。
摘掉,并加一条断言:**启动参数里不许带调试开关。**



### 换画面那块搬到画面右下角

像视频播放器的画质菜单:收起来只是一小块半透明的牌子,写着现在是哪一种;
点一下往上弹出三项,当前那项带 ✓,每项下面一行小字是"什么时候用它"。

**为什么现在搬**:后面要做全屏,那时所有控制层都得和主屏融合,顶栏没地方待。

点别处、按 Esc 都收起来 —— 菜单开着会挡住画面右下角,而那儿常常是页面内容。
键盘能用。只有一种可选时整块不画。

### DOM 重放里不再画第二个指针

rrweb 会照着录下来的鼠标轨迹画一个自己的指针(`.replayer-mouse`)——
而人自己的光标本来就在那儿,于是**画面上有两个**。

一个决定,两处落地:**源头不录**(鼠标是增量事件里最密的一路,不录就不传,
顺带省那份带宽)、**观看端不画**(那个元素 rrweb 是无条件建的,不录也在,
只是不动了,一个停在左上角的鬼影)。

关掉鼠标事件还有个附带好处:它连 focus/blur 一起关了,而那正是之前
把观看端键盘焦点夺走的那一类 —— 等于给 0.14.0 那道 `inert` 加了第二层。



**三条腿起 session 就备好,人切模式只决定哪条通道在传。**

VNC 那条本来就是起 session 时定的(X 显示和有头 chrome 事后加不上),
而 DOM 那条却是"等你切过去才装" —— 那时页面早跑完了,剩下的全是补救。
现在记录器**三种模式下都装、起 session 就录**。

代价是每个 session 往页面里注一份记录器(565 KB)并一直录着。
**带宽不受影响** —— 事件只在有人接 `/channel/rrweb` 的时候才发。

### 中途切到 DOM,三个 bug

写 `v2_browser_simple_dom`(JPG 进百度 → 切 DOM)撞出来的:

| | 人看到什么 |
| --- | --- |
| 中途切什么都没装 | **一片空白**(代码里只打了句 "要等下一次导航" 的 warning) |
| UMD 被页面的模块加载器劫走 | 同上。百度有 AMD 加载器,rrweb 的 UMD 走 AMD 分支**不设全局** |
| **尺寸没跟着换过去** | 画面塌了 —— 重放**其实在放**(iframe 1380x774),而容器是 0x0 |

第三个和之前那条 VNC 旧伤同族:"显示哪个元素"和"连哪条上游"分开了,
**漏了第三件 —— 尺寸**。它只在 `hello` / `cast` 到达时写一次,
人中途切过去的话,那一次早写在**切走的那个元素**上了。

### 升级之后上次的 tab 还在

**不是 tab 数据没清 —— 我们一条都没留。** 是 chrome 的 profile 目录里存着
"上次开着哪些标签页",而只要上次不是干净退出的(**升级时被 kill 正是这种**),
它下次起来就自己捡回来。`--disable-session-crashed-bubble` 挡不住那个,
它只是把气泡藏起来。

起 chrome 之前清掉 `Default/Sessions/` 和 `Preferences` 里的 `exit_type`;
**cookie、登录态、历史一个都不动** —— profile 留着本来就是为了不用重新登录。

实测 `kill -9` 之后重启:修前 3 个 tab(上次那个 `example.com` 回来了),
修后 1 个空白。

## 0.13.0

### DOM 那条腿:两个不报错的 bug

写 `v2_browser_dom` 的时候撞出来的,**两个都不报错**:

**资源全 404。** 快照里的地址被改写成根路径 `/api/res?u=…`,
而转发那条路由在 `/s/{sid}/api/res` 下 —— 百度首页 **25 个资源请求,0 成功**。
重放出来的是一棵**没有样式的**真 DOM:节点数、文字、标题**全都对**,
只有样式表和图片是 0。人只会觉得"这页怎么这么丑"。改成相对地址。

**键盘焦点被重放的 iframe 夺走。** rrweb 会把录下来的 focus 事件放出来
(百度一加载就 focus 搜索框),它在 iframe 里调 `.focus()` ——
于是人敲的每一个字都进了那棵**只读**的树,一个都到不了服务端。
`pointer-events: none` 只挡鼠标,焦点是另一条路;挡它要 `inert`,
而且**必须设在 iframe 自己的文档里**。

于是"只读是结构性的"这句话现在才是真的:**点不到,焦点也拿不走。**



**画面不是那个 X 桌面,是桌面里那个浏览器窗口。**

0.12.0 把"像素对齐"做成了"让人的窗口去改 X 显示的尺寸"。那条链有四个环,
每一环都真断过一次,而且**断得都没有声音**;它还逼出两个代价:

- Xvfb 的显示尺寸改不了 → 只好换 **Xorg + dummy** → 多一套依赖,
  而且它起得慢,导致 VNC **间歇性起不来**(0.12.1 修的那个)。
- 窗口正好等于屏幕时,**chrome 会退一像素** → 画面右下各露一条缝,
  只能多要一像素去盖住。

**换个想法,这些一起没了:** 显示一次开够(4K)就不动,浏览器窗口在里面调,
观看端只取左上那一块。

于是 **VNC 和 JPG 变成同一个心智模型:画面多大由我们定。**
一边改视口,一边摁窗口,别的都一样。

一起没掉的:

| | |
| --- | --- |
| Xorg + dummy 依赖 | **回到 Xvfb**,装的东西和 0.11.0 一样 |
| VNC 间歇性起不来 | 没了 —— Xvfb 一秒内就起来 |
| 失败时留下孤儿 X server | 没了(而且 `stop()` 现在按进程组收一次,兜底) |
| 页面比画面宽一像素 | 没了 —— 窗口永远比屏幕小,那条硬规则碰都碰不到 |
| `configure-display` / `desktop_mode_size` / `window-resized` | 上行白名单少一条,客户端少一整段 |

**代价是内存:** 屏幕一次开到 `3840x2160`。实测 Xvfb 的 RSS ——
1080p 70.5 MiB、2560x1600 78.4 MiB、4K 94.3 MiB。4K 比 1080p 多 24 MiB,
而同一个 session 里那个有头 chrome 要 700 MiB 上下。
这 24 MiB 买的是**像素对齐对 4K 用户也成立**。

## 0.12.1

**0.12.0 的 VNC 会间歇性起不来。** 换成 Xorg + dummy 之后漏了一件事:

```
RuntimeError: could not connect to X server on display ':80' after 1 seconds
```

xpra 等虚拟显示的那个上限(`XPRA_VFB_WAIT`)**是按 Xvfb 定的** —— Xvfb 一秒内
就起来了,而 Xorg + dummy 要加载模块、探 udev、跟 systemd-logind 打交道,
这台机器上实测 **3.8 秒**。所以它有时候赶得上、有时候赶不上,
**测试跑十遍绿八遍**,而失败那两遍是整个 session 起不来。

改成由我们给这个上限(20 秒)。这不是"睡一个秒数":xpra 在这段时间里
**轮询到就走**,这个数只是放弃的界限。

顺带修掉一个更难看的:等超时之后 **xpra 把已经拉起来的 Xorg 丢在那儿不管**。
杀 xpra 那个进程收不走它 —— 显示没起来时 `xpra stop` 无从下手,SIGTERM 只到
xpra 自己,Xorg 被过继给 init,继续占着那个显示号。实测一次失败留下三个,
**一句话都没有**。现在 `stop()` 最后按进程组收一次(起的时候就
`start_new_session=True`,那一组里只有它和它的孩子)。

## 0.12.0

**人的窗口多大,里面那个浏览器就多大。**

ttyd 把终端调成你窗口那么大,tmux 里的 80 列就真是 80 列。这一条我们原来
只在 JPG 上做到了 —— VNC 那条腿上,人把窗口拉大只是把同一张 1024×768 的图
放大,越拉越糊,**而且一句话都没有**。

现在两条腿都对齐:**人窗口里给画面留的那块地、画面元素占的地、帧本身的像素,
三个数相等。**

### 虚拟显示从 Xvfb 换成 Xorg + dummy

根因在最底下:**Xvfb 的显示尺寸是死的。** 整个显示只有一个 RANDR 模式,
`xrandr --newmode` 静默无效、`--fb` 直接 `BadValue`。于是
`--resize-display` 在它上面永远空转。dummy 驱动可以:任意模式加得上、
切得动,屏幕真跟着变。

所以依赖变了,**装的东西不一样了**:

```console
apt install xpra xserver-xorg-core xserver-xorg-video-dummy python3-pil
yum install xpra xorg-x11-server-Xorg xorg-x11-drv-dummy python3-pillow
```

`webmuxd install` 会装。探不到就报出来,指名道姓说缺哪个包 ——
**不偷偷退回一个对不齐的画面**。

### 那条链上还断了四处

修一处不够,那条链每一环都断着,而且断得都没有声音:

| 断在哪 | 表现 |
| --- | --- |
| 发的是 `desktop_size` | `start-desktop` 的服务端把这个包**明确当空操作**;要发 `configure-display` |
| 握手里没有 `desktop_mode_size` | 连上第一眼就是 xpra 自己的默认 1920×1080 |
| 客户端把 `window-resized` 的包位读错 | 服务端发了,客户端整包丢掉,画面尺寸停在连上那一刻 |
| chrome 不跟显示走 | `screen.width` 它读得准,**但窗口纹丝不动** |

最后那一下要三条 CDP 命令,顺序是死的:
`normal → bounds → fullscreen`。直接给全屏窗口设尺寸会被**静默丢掉**;
停在 `normal` 则是 kiosk 的地址栏标签栏回来占掉 87 像素。

验在 [tests/v2_browser_pixel_align](tests/v2_browser_pixel_align/),
JPG 和 VNC 各一遍。

## 0.11.0

**起/停/重启收成二级,别的照旧。**

```console
$ webmuxd server start --port 7900
$ webmuxd server stop
$ webmuxd server restart          # 端口沿用记着的那个
```

只有这三个动。`click` / `goto` / `snapshot` 一天打几十遍,多一层只是让每次
都更长 —— tmux 和 agent-browser 也都这样:**热的动词平铺,成组的收进二级**。

为什么偏偏是这三个:**`start` 是我们自己发明的**(tmux 没有,它的 server
隐式起;我们因为端口必须显式给才加了它)。发明了 `start` 就欠一个 `stop`,
而 `stop` 被页面那个"停止加载"占着 —— 于是一个刚 `start` 完的人打 `stop`,
拿到的是「这个 server 上还没有 session」,**方向完全反了**。
收进二级之后这条歧义自己没了。

搬走的旧名字会说自己搬去哪了,不是让人回 `--help` 里找:

```console
$ webmuxd start --port 7900
✗ bad_request: server 那一族收成二级了:`webmuxd server start --port 7900`
$ webmuxd kill-server
✗ bad_request: → `webmuxd server stop`
```

### 说了 http 就是 http

新版 Chrome 默认开着 HTTPS-First:你请求 `http://`,它先替你换成 `https://`
试,失败就停在一张「This site doesn't support a secure connection」上。

**我们把它关了。** 不关的话那条路是**封死的**,不是"少一个选项" ——
那张 interstitial 从我们这边看是**空文档**(控制器是空壳、`document.body`
长度 0、AX 树空,**有头无头一样**)。人在画面里看得见那两个按钮、点得动;
我们够不着。

> 这是关掉一个安全特性,所以 `webmuxd info` 里报着这一行。
> 判据是那条老规矩:**显式传入优先** —— 和「端口由你给」同一条。

### 打不开的时候会说打不开

```console
$ webmuxd goto -t demo http://nonexistent.invalid/
✗ nav_failed: http://nonexistent.invalid/ 打不开:net::ERR_NAME_NOT_RESOLVED
  域名解析不了 —— 地址打错了,还是这台机器没有 DNS?
```

以前**打不开的站会打一个 ✓**:`Page.navigate` 的 `errorText` 被整个扔掉,
而 `url` 还显示成目标地址(Chrome 的错误页保留原地址),`capture` 是空的。
**对 agent 就是"什么都没发生,而且不报错"。**

`NavFailed` 这个类、它的 `net_error` 字段、502 那条映射一直都在 ——
**契约写好了,线没接。** 退出码 **8**,和 4(改定位)是两条不同的下一步。

**光看 `url` 判断不出成没成** —— 唯一可靠的是退出码。

### 读快了 7 倍

`get` / `is` / `count` 现在**不 settle、也不给人让路**:

| | 之前 | 现在 |
| --- | --- | --- |
| `get value` | 2.43s | **0.34s** |
| `click`(真的改了页面) | 2.49s | 2.49s —— 该等 |

`settle` 的意思是"做完之后等页面稳下来",而读没有"做完";
`busy_human` 的意思是"人正在操作,别抢方向盘",而读不跟人抢 ——
人一边打字一边读页面,正是该允许的事。

> **凡是按"改不改东西"分的规矩,都要问一遍读该不该在里面。**

### 会改到你的代码

| 以前 | 现在 |
| --- | --- |
| `webmuxd start --port 7900` | `webmuxd server start --port 7900` |
| `webmuxd kill-server` | `webmuxd server stop` |
| — | `webmuxd server restart` |
| `goto` 打不开也回 0 | 回 **8**(`nav_failed`) |

`webmuxd info` 没搬 —— 它答的是"这台机器什么情况",不是对 server 的操作。

## 0.10.0

**这一版是"问一个,别抓一整页"。**

新增四条命令,照 [agent-browser](https://github.com/vercel-labs/agent-browser)
的源码对齐:

```console
$ webmuxd snapshot -t demo -i          # 这一页上有什么,每样带一个 @e1
@e1   link      "登录"
@e13  textbox   "" 
@e14  button    "百度一下"

$ webmuxd fill  -t demo @e13 webmuxd   # 清空再填,一条顶掉 click + type
$ webmuxd get value -t demo @e13       # 问一个值
webmuxd
$ webmuxd is visible -t demo @e13      # 问一个状态,答案在退出码里
true
$ webmuxd get count -t demo --css h3   # 数一数
10
```

### `@e1`:跨命令活着的号

`snapshot` 给每样东西发一个号,下一条命令直接拿去用 ——
不用再描述"那个登录按钮"是哪个。

**号只增不重用。** 第二次 `snapshot` 从 `@e26` 接着发,不从 `@e1` 重来。
重用省事,但它把"拿着过期的号去点"从一个**报错**变成一次**点错东西**。

号还绑着那份文档。跨页之后旧号会说清楚:

```console
$ webmuxd click -t demo @e13
✗ not_found: @e13(那时是 textbox「」)是上一个页面上的号 —— 页面换过了,重新 snapshot 一次
```

> 光验"那个节点还在不在"不够 —— **Chromium 会把节点句柄复用给新文档里的
> 节点**,于是导航之后拿旧号去点会**成功,而且点中的是另一个东西**。撞到过。

### 快了

| | 之前 | 现在 |
| --- | --- | --- |
| 真实网站上点一下 | 5.65s | **1.68s** |
| `get value` 这类读 | (只能抓整页,3–15 KB) | **0.34s** |
| 浏览器起不来多久才报错 | 30s,而且说的是错的 | **0.02s** |
| `sess.detach()` | 卡 2 秒 | 立刻 |

**动作慢的原因是 `network_idle` 永远不收敛。** 它要等在飞请求归零,而任何
带埋点或长连接的站都不会归零 —— 于是每个动作都烧满 5 秒超时,然后只剩
0.2 秒留给"页面还在不在变"这个真问题。现在等网络最多 1 秒,剩下的预算全给
DOM。

**读的动作不再 settle。** 读什么都没改,没有"做完",没什么可等的。

### 修的

- **VNC 那条画面断了不重连** —— 网抖一下(合盖、切 WiFi、进隧道),
  画面就永远停在最后一帧,只能刷新页面。两条通道一条会重连一条不会,
  而代码里**没有一句话说这是有意的**。
- **换画面切不回去** —— `VNC → JPG → VNC`,第二次点 VNC 按钮画面纹丝不动,
  **没有报错,console 也是干净的**。"显示哪个元素"和"连哪条上游"两件事缠在
  一起,漏了一条路。
- **观看页的画面对读屏软件是哑的** —— `<img alt="">` 的意思是"这张图没信息,
  跳过它",而它是整页唯一有信息的地方。
- **浏览器起不来时干等 30 秒,还说错话** —— 说"浏览器起来了但 CDP 没监听",
  而它已经退了。现在盯着进程,死了立刻报,并且分清是哪一种。
- **客户端超时和服务端一样长**,于是我们的错误信息永远到不了人手上 ——
  拿到的是一串 urllib traceback。客户端改成 60 秒。

### 会改到你的代码

| | |
| --- | --- |
| `webmuxd click -t demo @e1` | **新写法**,老的按文字/role 定位一个字没变 |
| 每个动作之后的等待 | 默认从"最多 5 秒等网络"变成"最多 1 秒等网络 + 剩下等 DOM"。**要老行为传 `settle={"strategy":"network_idle","timeout_ms":…}`** |
| `Webmuxd(timeout=)` | 默认 30 → 60 秒 |
| `locate.FILTER_VERSION` | 1 → 2(元素筛选多了"看结构"那一档) |

`tab.snapshot()` / `tab.count()` 是新的;`tab.extract()` 多了
`value` / `box` / `visible` / `enabled` / `checked` 几种 mode。

## 0.9.0

**一个 server 一个口。** 先起服务,再往里加 session —— 和 tmux 一样。

```console
$ webmuxd start --port 7900
server  →  http://127.0.0.1:7900/   (还没有 session:webmuxd new --id demo)

$ webmuxd new --id demo
demo  →  http://127.0.0.1:7900/s/demo/
```

打开 `http://127.0.0.1:7900/` 是那张 session 列表(还没建的时候它告诉你怎么建),
点进去就是那个浏览器。**四个 session 从前要八个端口,现在一个。**

以前"一个 session 一个端口"不是设计,是 v1 那个 kasm 镜像的 web 口
不归我们控制;画面换成自己产的之后,那条硬约束早就没了,只是形状留着。

### 会改到你的代码

| 以前 | 现在 |
| --- | --- |
| `webmuxd new --id work --port 7900` | `webmuxd start --port 7900` 然后 `webmuxd new --id work` |
| `Webmuxd()` + `session(id=, port=)` | `Webmuxd(port=7900)` + `session(id=)` |
| `http://host:7900/api/tabs` | `http://host:7900/s/work/api/tabs` |
| — | `webmuxd kill-server` 停 server 和全部 session |

`port=` 传进 `session()` 会**当场报错并说端口去哪儿了** —— 不静默吞。

**server 不按需自启。** tmux 能自启是因为它用 socket,没有端口要挑;
我们有,而这个项目那条规矩是"端口由你给"。没起 server 时,
`webmuxd new` 报错并告诉你该跑哪一行。

### 读的那一面只剩一张图和正文

```
GET /s/work/api/screenshot   → image/webp
GET /s/work/api/text         → text/plain
```

`/api/observe`、`tab.observe()`、`webmuxd observe` **都没有了**。
那是一包"关于 agent 该怎么用浏览器的意见" —— 筛过的元素表、编好的号、
150 个上限、一次观测的 id。判据是那句老话:**tmux 会做这个吗?**
它有 `capture-pane`,就是这两样。

**元素表没消失,它在定位那一侧**:`tab.click("提交订单")` 就是拿它做的。
歧义时回候选,**拿 `role` + `name` 重试**:

```python
try:
    tab.click("订单")
except NotFound as e:
    tab.click(e.details["candidates"][0])
```

跟着一起去掉的是**按编号定位**(`{"element": 12, "observation": "..."}`):
编号只在一次快照里成立,没有"一次观测"之后那道挡陈旧编号的板子没了落点 ——
**留着键而挡不住,比没有这个键更坏**。

同时:**观测不再往页面上画框**。以前是在活页面铺一层带编号的框再拍,
于是正在看的人会闪一下,DOM 模式下那层还会被录进重放流撤不掉。
量出来的:静止页面上连着看,三次 observe 推了 3 条带标注层的事件给观看者;
现在是 0 条。要 Set-of-Mark 图,拿 `bbox` 自己叠。

### DOM 那条画面其实一直是坏的

`--transport dom` 起的 session,`/channel/rrweb` 连得上、**一条事件都不来**,
而且全程不报错。两个真因,一个盖着另一个:

- **`Runtime.enable` 全项目一处都没调过。** `addBinding` 照样成功、页面里那个
  函数照样在、页面照样调它 —— 而 `bindingCalled` 根本不推
- **binding 每次导航都没了。** 旧注释写"不一定活过导航",量清楚了是**每次都不活**

修法是两边配合:服务端订 `executionContextCreated` 每个新文档补一次;
页面那段脚本是 document-start 的、必然更早,所以**先攒着等**。
顺手把那个吞异常的 `catch (_) {}` 拆了。

### 内部:两棵树,和一个 models.py

代码摆法整个重来([docs/v2/works/j-layout.md](docs/v2/works/j-layout.md)):

- **按语言分两棵树**:`webmuxd/`(Python)· `webmuxjs/`(JS)
- Python 那棵**照 requests 平铺** —— 七个子包没了,一个文件一件事
- **`webmuxjs/client/` 是一个真的前端工程**:TypeScript、vite、43 个 vitest,
  和 Python 对拍的 fixture。构建产物在打 wheel 之前现建,
  **"忘了先构建"那种漏不可能发生**
- **`models.py`** 装下所有跨边界的数据 —— 以前同一个概念服务端一份、
  SDK 一份、JS 一份

**对外一个字没改**:包名、CLI 名、`pip install webmuxd` 都一样。

## 0.8.0

**画面从两种变成三种,而且可以随时切。**

使用者看到的是三个词 —— **JPG / VNC / DOM**。技术名字(screencast / xpra /
rrweb)不再出现在界面、CLI 和报错里:它们说的是我们怎么实现的,
而使用者要判断的是"这三个有什么不一样"。

| | 一句话体感 | 什么时候选它 |
| --- | --- | --- |
| **JPG** | 一张一张的图,什么都显示得出来 | 拿不准就用它;有视频、有 canvas 的页面 |
| **VNC** | 像远程桌面,连续、跟手 | 动画、视频、大量滚动 |
| **DOM** | 传的是网页本身,字最清楚、最省流量 | 文字为主的页面;网络差的时候 |

`--transport jpg|vnc|dom`,旧名字继续认但一律归一。界面上点一下就切,
**切的只有画面这一样东西** —— 输入、光标、tab、原生 UI 一行不动。

**能切到哪几种是起 session 时定的**,不是运行时算的:VNC 要一个真实的
X 显示,无头浏览器没有。所以起的时候那个选择不是"用哪种",是"以后能选哪几种"。
切不了就报错并说清为什么、怎么才能有 —— 不悄悄留在原来那种。

### DOM 那条:三个"不报错、只是不工作"

做这条的时候连撞三个,每个都是日志和测量纠回来的,不是想出来的:

1. **`--transport` 没传到 sessiond。** `--transport dom` 一路顺利起来,
   而 sessiond 用的是默认 jpg。
2. **注入登记成功,脚本从不执行。** `addScriptToEvaluateOnNewDocument` 只对
   之后创建的文档生效,而 attach 常常发生在导航之后 —— 那段脚本在等一个
   永远不会来的"下一个文档"。
3. **binding 不一定活过导航。** 记录器跑起来了,但 `emit` 抛进它自己的
   `try/catch`,事件被静默丢掉,表现和"根本没注入"一模一样。

第 2 条的修法(新 target 先暂停、注入完再放行)**顺带补掉了 shim 和光标探针
一直存在的同一个竞态** —— 只是以前没人撞见。

留了一份复盘在 `docs/v2/issues/`,记的是那三条教训:**"登记成功"不等于
"会执行"**、**吞异常的 catch 会把问题藏死**、**先验再改**。

### 别的

- **通道各自一条连接**:`/channel/cdp` · `/channel/xpra` · `/channel/rrweb`
  (旧的 `/api/view` `/xpra` 留着)。DOM 那条**只下行,而且是结构上没有上行**
  —— handler 里根本没有接收端,不是过滤
- **install 的产出是一份路径表**:xpra 的 bin / 它自己的解释器(读 shebang)/
  版本、Xvfb、字体目录、rrweb。记录格式 2→3
- **rrweb 归 install 下,不在运行时现下**,而且版本钉死 2.1.1 ——
  `@latest` 意味着两台机器可能拿到不同版本,而记录器和重放器必须同一版
- **输入 25ms 聚批**:同批只留最后一个移动,滚轮累加(丢掉的每一格都是真滚过的
  距离),按下前先把攒着的位置冲掉,回执永远不进批
- 设计稿 `c-pixels` 改名 `c-view`:接缝的定义是"画面从哪来",不是"传的是不是像素"

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

顺带新增 [works/13](docs/v2/works/i-agent-surface.md):给 agent 的操作面
和一条行为流,横向看了七家云浏览器。这个 bug 就是写那一篇时量出来的。

## 0.7.1

**xpra 那条路上 WebGL 是关的 —— 换默认的时候差点把它弄丢。**

有头的 Chrome 不像 headless 那样会自己退到 SwiftShader:Xvfb 上没有 GLX/DRI,
它直接把 WebGL 整个关掉(`SystemInfo.getInfo` 报 `webgl: disabled_off`)。
也就是说 0.7.0 把默认换成 xpra 之后,**WebGL 页面是白的**。

反直觉的一点:`--disable-gpu` **救不回来**,有头下它关得更彻底。
实测三种组合,只有 `--use-gl=angle --use-angle=swiftshader` 能把它救回来。

这个是写设计稿时量出来的,不是有人报的 —— 所以顺带补了
[works/11 §0](docs/v2/works/c-view.md):xpra / Xvfb / Xorg 各是什么、
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
滚动是整屏重发([works/12 §9](docs/v2/works/c-view.md))。
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
([works/12 §9](docs/v2/works/c-view.md))。

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
右下各 2 像素在可见区域外([works/12 §10](docs/v2/works/c-view.md))。

## 0.5.6

**画质下限从 5 提到 25,`--dsf` 变成开关。**

### 下限:抄阈值的时候把下限也抄了,那一条抄错了

原来的降级路径是 `80 → 60 → 40 → 20 → 5`。**q5 是马赛克,根本没法用**,
而且 `20 → 5` 是个断崖。降质的意义是"糊一点但还能操作",不是"糊到看不清"。

25 不是拍的 —— BrowserBox 自己在 Tor 模式下就把下限压到 25
([works/01 §4](docs/v2/works/c-view.md)),那是它认为的"还能用"的底。
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
([works/02 §4](docs/v2/works/c1-quality.md))。页面底下那条状态栏就是
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
留作别名,免得 [works/07](docs/v2/works/h-runtime.md) 里那条命令突然报错)。

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
推荐的隔离路子(把 webmuxd 装进容器,[works/07 §2](docs/v2/works/h-runtime.md))
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
而那是选 Chrome for Testing 的**唯一理由**([works/07 §4.1](docs/v2/works/h-runtime.md))。

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
