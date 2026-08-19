# d · install:一次探清楚,之后不再猜

**一句话**:`install` 的产出**不是"装好了",是一份路径表** ——
之后每次起 session 都照着它走,不再 `which` 一遍、不再猜。
能下载的下载(浏览器、字体),下载不了的该装还是装(X server、xpra),
**判据是这东西是数据还是程序**,不是"动不动系统"这种洁癖。

## 1. 产出:一份路径表

```jsonc
// ~/.webmuxd.json —— 这不是配置文件,是这台机器的事实
{
  "version": 3,
  "at": "2026-08-19T00:19:48Z",

  "browser": {
    "path": "~/.cache/webmuxd/chrome-152.0.7977.42/chrome-linux64/chrome",
    "version": "152.0.7977.42",
    "source": "chrome-for-testing"
  },
  "fonts_dir": "~/.local/share/fonts",        // 我们下的字体放这儿

  "xpra": {
    "bin":    "/usr/local/bin/xpra",
    "python": "/usr/bin/python3",             // 读它的 shebang 得到的
    "version": "6.6"
  },
  "xvfb": "/usr/bin/Xvfb"
}
```

每一行都要能回答"runtime 拿它干什么":

| 键 | 干什么 | 不定下来会怎样 |
| --- | --- | --- |
| `browser.path` | 起浏览器 | 每次去 `~/.cache` 和 `PATH` 里翻 |
| `browser.version` | 钉死版本,换版本要先跑一遍验证 | 升级了不知道 |
| `fonts_dir` | 判断中文字体齐不齐 | — |
| `xpra.bin` | 起那个进程 | 每次 `which xpra` |
| **`xpra.python`** | **探/装 PIL 要用它**,不是我们的解释器 | 探错解释器 —— venv 里明明能跑却报不可用 |
| `xvfb` | 传给 `--xvfb=`,**不让发行版配置替我们选** | 同一条命令在两台机器上跑的是两个 X server |
| `xpra.version` | 协议兼容(我们写死 rencodeplus) | 老版本握手失败,报错不指向版本 |

**"每次现探"的问题不是慢,是探的结果可能和上次不一样。** 用户装了个新 xpra、
改了 `PATH`、在 venv 里跑 —— 每一条都会让这次和上次不同,而**报错不会告诉你
"这次用的和上次不是同一个"**。定下来就没这回事。

> 三条老规矩不变:**键在 = 探到了,键不在 = 没探到**(不写 `ok:false` 这种空壳);
> **传进来的赢**(显式给了路径就不看记录);**记录会撒谎**(你 `rm -rf` 了缓存它不知道),
> 所以照着它起,起不来就报错**并让人重跑 install**,不静默重探。

## 2. 每样东西从哪来

| | 来源 | 落在哪 |
| --- | --- | --- |
| Chromium | **下载**(Chrome for Testing 的 zip) | `~/.cache/webmuxd/chrome-<版本>/` |
| 中文字体 | **下载** | `~/.local/share/fonts/` |
| chrome 要的系统 `.so` | **系统包** | 系统 |
| Xvfb | **系统包** | 系统 |
| xpra | **系统包**(或用户自己 pip 编译) | 系统 |
| PIL | **pip**,装进 `xpra.python` | 那个解释器 |

判据只有一句:

> **是数据,就下载;是要跑起来、还要吃一堆系统库的程序,就装。**

- 字体是数据 —— 一个 `.otf` 丢进 `~/.local/share/fonts` 再 `fc-cache`,
  **不用 root**(fontconfig 默认就认这个目录,实测过)。所以它不该走包管理器。
- Xvfb 是程序,而且**它自己动态链接 34 个库**;chrome 直接依赖 **85 个 `.so`**。
  "下载一个 Xvfb"实际是下载半个发行版,还要保证和这台机器的 libc、
  X 扩展版本对得上。这类东西**只能交给包管理器**。

真要把这些也变成下载,唯一的路是我们自己构建并托管一套自包含产物 ——
那是养一条构建流水线,不做。

## 3. 落地顺序

`install` 从头到尾就这七步,每步的失败都不阻断后面的(**能探多少探多少,
最后一次性把缺口说全**)。

### ① 先看这台机器能不能装

探 `apt-get` / `dnf` / `yum`(按这个顺序),再探能不能提权:
**root,或者不要密码的 `sudo`** —— 要密码的不算,`install` 不是交互式的,
卡在密码提示上比直接说"没权限"更糟。

结果决定后面几步是**装**还是**只打印那一行**。

### ② 浏览器:测速选源 → 下载 → 解压 → 写标记

```
探几个下载源的吞吐(不是延迟 —— 下一百多 MB 时握手快 20ms 一文不值)
   → 挑最快的那个下载
   → 校验 + 解压到 ~/.cache/webmuxd/chrome-<版本>/
   → 最后写 INSTALLATION_COMPLETE
```

**标记是最后一步,不是解压完就算。** 目录里有个 `chrome` 不等于装完了 ——
解压到一半被 Ctrl-C、磁盘满、进程被 OOM 杀掉,都会留下看着挺像的一堆文件。
**没有标记就当没装过。**(这条是实测出来的:目录里只放一个已 chmod 的
`chrome`、别的全缺,旧的判断照样说"装好了"。)

失败时**把目录删干净**,不留半个解压结果;然后把原因**整句**打出来 ——
DNS 不通、403、连接超时,这三种的下一步完全不同。

### ③ chrome 的系统库:探 → 缺就装

`ldd` 那个二进制,`not found` 的就是缺的。缺了就按 ① 的结论装一整组
(不去算"哪个包提供 libnss3" —— 那要 `apt-file` / `dnf provides`,
慢而且不一定装得到;整组装一遍是幂等的)。

装完**重新探一遍**。`apt-get` 返回 0 只说明命令没报错,
**判据永远是探测结果,不是安装器的退出码。**

### ④ 字体:下载,不走包管理器

```
探:fc-list :lang=zh 有没有东西
缺:下载一个 CJK 字体 → ~/.local/share/fonts/ → fc-cache
```

这一步**不需要 root**,所以它和 ① 的结论无关 —— 有没有权限都能做完。

> 中文字体缺了**不报错,只是难看**(全是豆腐块),
> 是这几项里最容易被当成 bug 的一个。

### ⑤ xpra 那条腿:xpra / Xvfb

两个都探可执行文件。缺了按 ① 装:

```
Debian/Ubuntu   apt install -y xpra xvfb python3-pil
RHEL/CentOS     yum install -y xpra xorg-x11-server-Xvfb python3-pillow
```

**两个家族的包名都要给**(`xvfb` vs `xorg-x11-server-Xvfb`),
只说一个的话另一边的人得自己猜。

xpra 在 RHEL 系**不在基础源里**,装不上时要分清是"源里没这个包"还是"没权限" ——
前者要加源(给出 xpra.org 的地址),后者要 sudo。**两者的下一步完全不同。**

### ⑥ PIL:装进 xpra 的那个解释器

`xpra` 是个带 shebang 的脚本,读第一行拿到它的解释器。
**探 PIL 要探那个解释器,不是我们的** —— webmuxd 常在 venv 里,
两边可以完全不同(venv 里没有而系统有,就会拦下一个本来能跑的模式)。

读不出 shebang(比如它是个二进制)就跳过这一项:**不知道就别拿猜的答案挡人。**

### ⑦ 把路径写进记录

前六步解析出来的东西一次性落盘(§1 那张表)。**探不到的键就不写。**

## 4. 输出长什么样

一屏,一行一样东西,状态在右边;缺了的话紧跟着**完整到可以直接粘的那一行**:

```
探测环境…
  python     3.11.2                                 ✓
  包管理     apt-get,可以装                         ✓
  浏览器     chrome 152.0.7977.42                   ✓
  共享库     齐                                     ✓
  中文字体   下好了 → ~/.local/share/fonts          ✓
  xpra       缺 Xvfb                                ⚠
     装上:sudo apt install -y xpra xvfb python3-pil
     不想装的话:webmuxd new … --transport screencast
  记录       ~/.webmuxd.json
```

**能装的时候直接装完再报结果**,不是打印一行让人自己跑 ——
探到缺了却不装,等于把活原样退回去。**只有没权限时才退化成打印。**

## 5. 幂等和并发

- **"检查"和"安装"是同一个命令**,不需要一个 `doctor`。再跑一次就是重新探一遍。
- **没有记录也能用** —— `install` 省的是重复开销,不是"必须先装"。
  写脚本的人不该被一个 CLI 步骤挡住。
- **目录锁还没做**:两个终端同时 `install` 现在会互相踩。

## 6. 还没定的

| | |
| --- | --- |
| 记录扩到 §1 那张表 | 现在只有 `default_browser`,xpra / Xvfb / 解释器全是每次现探 |
| 字体下哪一个 | Noto CJK 全量很大,子集够不够用没量过 |
| 目录锁 | 两个终端同时 install |
| 用 `apt-get install -s` 探依赖 | 比 `ldd` 严格:报包名不报 `.so` 名,而且不用先有浏览器 |
| 探服务端的图像编码器 | 没带 webp/jpeg 的 xpra 只剩 rgb —— **画面能出但带宽爆炸,而且不报错** |
| Chrome for Testing 的条款 | 它把自己定位成测试/自动化用的构建,我们的用法算不算落在里面 |

## 7. ↔ 别处

| | |
| --- | --- |
| 为什么需要一整套 X | [c §6](c-pixels.md#6-这一套东西是什么) |
| 那条腿起不来时报什么 | [c §10](c-pixels.md#10-默认走哪条) |
| 落地在 | [`browser.py`](../../../webmuxd/browser.py) · [`env.py`](../../../webmuxd/env.py) · [`cli/install.py`](../../../webmuxd/cli/install.py) · [`cli/deps.py`](../../../webmuxd/cli/deps.py) |
| 测试在 | [`tests/installing/`](../../../tests/installing/) |
