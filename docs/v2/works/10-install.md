# 10 · playwright 的 install 有什么讲究

**一句话**:它下的**不是**系统包,是一个自带全部依赖的 zip,解压到用户缓存目录 ——
但它**同时**保留了一条装系统包的路,而且和前者**刻意分开**。
这一篇把它的机制逐条拆开,末尾给出我们该抄什么、不该抄什么。

材料全部来自 `microsoft/playwright` 主干源码(2026-08-18 拉的),
不是二手总结:`browsers.json`、`src/server/registry/index.ts`、
`registry/browserFetcher.ts`、`registry/dependencies.ts`、`registry/nativeDeps.ts`、
`bin/reinstall_chrome_stable_linux.sh`。

## 1. 先回答:下的是 bin 还是 rpm

**两条路都有,而且是两个不同的命令、两套不同的保证。**

| | `playwright install chromium` | `playwright install chrome` |
| --- | --- | --- |
| 下什么 | **一个 zip**(自带依赖的完整构建) | **`.deb`**,从 `dl.google.com` |
| 装到哪 | `~/.cache/ms-playwright/<name>-<revision>/` | **系统里**,`apt-get install` |
| 要 root 吗 | **不要** | **要** |
| 版本 | **钉死**,写在 `browsers.json` | `_current_`,**钉不住** |
| 平台 | Linux / mac / Windows | **只有 Ubuntu / Debian,而且只有 x64** |
| 叫什么 | 浏览器 | **channel**(还有 `chrome-beta` / `msedge` / …) |

那个 `.deb` 的脚本很短,一眼能看完(`bin/reinstall_chrome_stable_linux.sh`):

```bash
if [[ $(arch) == "aarch64" ]]; then echo "ERROR: not supported on Linux Arm64"; exit 1; fi
ID=$(bash -c 'source /etc/os-release && echo $ID')
if [[ "${ID}" != "ubuntu" && "${ID}" != "debian" ]]; then exit 1; fi
…
curl -L -O https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt-get install -y ./google-chrome-stable_current_amd64.deb
```

**这正是我们讨论过的那两种东西。** 阿里云那个
`mirrors.aliyun.com/google-chrome/` 托管的 `.deb` / `.rpm`,对应的是右边这一列 ——
它是"装系统里那个 Chrome",不是"下一个钉死版本的 CfT"
([07 §4.2](07-runtime.md#42-下什么从哪下))。

**playwright 把这两条分成两个命令,而不是把 `.deb` 当成 zip 的一个镜像。**
这个分法值得记下来:它们提供的保证根本不同,混在一个开关后面,
用户就分不清自己手上跑的到底是哪一版。

## 2. `browsers.json`:钉的到底是什么

```jsonc
{ "name": "chromium",                "revision": "1237",
  "browserVersion": "152.0.7977.8",  "title": "Chrome for Testing",
  "installByDefault": true },
{ "name": "chromium-headless-shell", "revision": "1237",
  "browserVersion": "152.0.7977.8" },
{ "name": "webkit", "revision": "2349",
  "revisionOverrides": { "mac14": "2251", "mac14-arm64": "2251" } },
{ "name": "ffmpeg", "revision": "1011" },
{ "name": "winldd", "revision": "1007", "installByDefault": false }
```

四件事:

**① 两层版本号。** `browserVersion` 是浏览器自己的版本(`152.0.7977.8`),
`revision` 是**他们的打包版本**(`1237`)。同一个浏览器版本重新打一次包,
`revision` 会变而 `browserVersion` 不变 —— 于是"换了构建"和"换了浏览器"是
两件能分开说的事。

**② chromium 的底座就是 Chrome for Testing。** `title` 字面写着。
和我们选的是同一个来源([07 §4.2](07-runtime.md#42-下什么从哪下))——
只是他们在外面套了一层自己的 CDN 和 revision。

**③ `revisionOverrides` 是"这个平台冻结在旧版"。** macOS 14 的 WebKit 停在 2251,
新的不给。而且用到冻结版本时会**打印一条警告**说"你这个浏览器不再更新了,
升级操作系统"——**不静默降级**,和我们那条规矩一样。

**④ 不只是浏览器。** `ffmpeg`(录像用)和 `winldd`(Windows 上查依赖的小工具)
走的是**完全相同的下载、缓存、版本机制**。这是个好设计:凡是"要从网上取、
要钉版本、要缓存"的东西,都归同一套。

## 3. arm64:CfT 没有,他们自己 build

`DOWNLOAD_PATHS` 里 x64 和 arm64 走的是两条完全不同的路:

```ts
'ubuntu24.04-x64':   cftUrl('linux64/chrome-linux64.zip'),        // Chrome for Testing
'ubuntu24.04-arm64': 'builds/chromium/%s/chromium-linux-arm64.zip', // 他们自己的构建
```

**这正好是我们现在直接报错的那个缺口** —— `browser.py` 里写着
"CfT 没出 linux-arm64 构建",然后抛出去让用户自己想办法。playwright 的答案是
**自己 build 一份放自己的 CDN**,代价是要养一条构建流水线。

对我们来说这条**不能照抄**:养构建流水线等于把"不发镜像、不维护别人的产品"
那条规矩([07 §4](07-runtime.md#4-webmuxd-install-下一个浏览器))换成一个更重的承诺。
arm64 上老实用系统的 chromium(`--browser`),并且**把这件事说出来**,
是更诚实的做法。

顺带注意 `DOWNLOAD_PATHS` 的键有多细:`ubuntu22.04-x64` / `ubuntu24.04-x64` /
`debian12-x64` … **精确到发行版的版本号**。原因是 glibc 和一堆系统库的版本不同,
一个 zip 不可能到处跑。

## 4. 缓存目录、并发、和那个标记文件

### 4.1 目录

```
~/.cache/ms-playwright/chromium-1237/          ← Linux
~/Library/Caches/ms-playwright/                ← mac
%USERPROFILE%\AppData\Local\ms-playwright\     ← Windows
```

`PLAYWRIGHT_BROWSERS_PATH` 换位置,**但 `0` 是个特殊值**:装进 npm 包自己的
`.local-browsers/`,也就是"跟着这个项目走,不共享"。相对路径会被解析成绝对路径,
而且是相对 `INIT_CWD`(`npm install` 的根)——注释里明说了为什么:
**安装时和运行时算出来的目录必须是同一个**。

### 4.2 `INSTALLATION_COMPLETE` —— 最值得抄的一条

```ts
export function browserDirectoryToMarkerFilePath(browserDirectory: string): string {
  return path.join(browserDirectory, 'INSTALLATION_COMPLETE');
}
```

它在两处被用:

- **下之前**:标记在 → 已经装好了,直接跳过
- **下之后**:标记不在 → **判定这次下载失败**,哪怕子进程退出码是 0

第二条是关键。**"文件存在"不等于"装完了"** —— 解压到一半被 Ctrl-C、磁盘满、
进程被 OOM 杀掉,目录里都会留下一堆看着挺像的文件。只有那个最后才写的标记
能区分"装完了"和"装到一半"。

而且清理逻辑也认它:`_deleteStaleBrowsers` 里,**没有标记的目录被视为不在用,
会被删掉**。

### 4.3 失败就删干净

```ts
if (await existsAsync(zipPath))         await fs.promises.unlink(zipPath);
if (await existsAsync(browserDirectory)) await removeFolders([browserDirectory]);
```

每次重试之前,**zip 和解压目录一起删**。不留半个状态给下一次去猜。

### 4.4 两把锁

**目录锁**(`registryDirectory/__dirlock`)防的是两个进程同时装。拿不到锁时的
报错还会**把锁文件路径和删除命令一起打出来** —— 这是"提示要指向下一步"的
好例子。

**唯一临时目录**(`mkdtemp('playwright-download-')`)防的是同一时刻的两个下载
互相踩 zip 文件。

还有一处很实际的细节:下载是 **fork 到子进程**里做的,注释说明了原因 ——
Node 有个 bug,未捕获异常时进程仍可能以 0 退出([issue 17394])。所以他们**不信
退出码**,而是回过头去查那个标记文件。

## 5. 镜像:他们是失败轮转,我们是先测速

```ts
const PLAYWRIGHT_CDN_MIRRORS = [
  'https://cdn.playwright.dev/dbazure/download/playwright', // ESRP CDN
  'https://playwright.download.prss.microsoft.com/dbazure/download/playwright',
  'https://cdn.playwright.dev',                             // 直连存储桶
];
```

```ts
const retryCount = 5;
for (let attempt = 1; attempt <= retryCount; ++attempt) {
  const url = downloadURLs[(attempt - 1) % downloadURLs.length];   // 轮着来
```

**5 次重试,依次轮转三个源。** 注意它**不测速** —— 第一个永远先试,
只有失败了才换下一个。

覆盖用环境变量,而且**按浏览器分**:`PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST` /
`_FIREFOX_` / `_WEBKIT_`,再加一个总的 `PLAYWRIGHT_DOWNLOAD_HOST`。
给了就**只剩这一个**(`mirrors = [customHostOverride]`)——
和我们那条"传进来的赢"是同一个语义。

### 两种策略解决的不是同一个问题

| | 失败轮转(playwright) | 先测速(我们,[07 §4.2](07-runtime.md#42-下什么从哪下)) |
| --- | --- | --- |
| 解决的 | **某个源挂了** | **某个源慢** |
| 代价 | 0 | 探测那 256 KB × 源数 |
| 什么时候不够用 | 源没挂但只有 200 KB/s,它会老老实实下完 | 源在探测时快、下到一半挂了,没有退路 |

**它们是正交的,该叠起来用。** 我们现在只有测速那一半 —— 探完排个序,
下载时按这个序失败轮转,是明显的下一步(§7)。

## 6. 依赖:`apt-get install -s` 比 `ldd` 好

我们现在用 `ldd | grep "not found"`,报出来的是**`.so` 名字**。
playwright 用的是另一招:

```ts
// `apt-get install -s` simulates the install: it does not need root and does not
// modify the system. Stdout includes one `Inst <package> ...` line per package
// that would be installed (i.e. that is currently missing).
const { stdout } = await spawnAsync('apt-get',
    ['install', '-s', '--no-install-recommends', ...packages], {});
for (const line of stdout.split('\n')) {
  const match = /^Inst (\S+) /.exec(line);
  if (match) missingPackages.push(match[1]);
}
```

**模拟安装,不要 root,不改系统,直接得到缺哪些包。** 三个好处:

1. 报的是**包名**,人能直接 `apt install` —— 而 `libnss3.so` 还要自己查是哪个包
2. **不需要浏览器已经下下来**(ldd 得有那个二进制才能跑)
3. 顺带把"装了但版本不对"也算进去

依赖表按**发行版版本**分,再按用途分组:

```
'ubuntu22.04-x64': {
  tools:    ['xvfb', 'fonts-noto-color-emoji', 'fonts-wqy-zenhei', …],
  chromium: ['libnss3', 'libnspr4', 'libgbm1', 'libatk1.0-0', …],
  firefox:  [...], webkit: [...],
}
```

只覆盖 5 个组合(`ubuntu22.04 / 24.04 / 26.04 / debian12 / debian13`,都是 x64),
别的平台**明说"不支持,当成 fallback 试试"**,不假装能装。

还有一张 `.so → 包名` 的映射表(约 200 条),给 Windows 那条路和报错用。

> 顺带:他们的 `tools` 里有 `fonts-wqy-zenhei` —— 中文字体是**默认装的**,
> 不像我们只是探一下报个警告([07 §4.3](07-runtime.md#43-系统依赖和字体照抄-playwright-的姿态))。

## 7. 我们该抄什么

| | 抄不抄 | 为什么 |
| --- | --- | --- |
| **`INSTALLATION_COMPLETE` 标记** | **抄了** | 写这篇时**实测过**:目录里只放一个已 chmod 的 `chrome`、别的全缺,旧的 `find()` 照样说装好了。现在标记是解压和 chmod **之后**才写的最后一步,`tests/installing` 有一条守着这个顺序 |
| **失败时删干净目录** | **抄了** | 原来只删那个 `.part`,解压出来的半个目录留着 |
| **`apt-get install -s` 探依赖** | **还没抄** | 报包名而不是 `.so` 名,而且不用先有浏览器。比 `ldd` 那条严格更好。现在是"缺一个就装一整组"(deps.py),够用但不精确 |
| **多个发行版家族** | **0.7.0 加了** | apt / dnf / yum。真机上撞的:RHEL 系不光包名不同(`xorg-x11-server-Xvfb` 而不是 `xvfb`),**xpra 默认用的虚拟显示都不一样**([12 §12.3](12-xpra-client.md)) |
| **下载源失败轮转** | **抄**,和测速叠起来 | 测速解决"慢",轮转解决"挂了",两个问题(§5) |
| **目录锁** | **抄一个简单的** | 两个终端同时 `webmuxd install` 现在会互相踩 |
| **两层版本号**(revision / browserVersion) | **不抄** | 我们不重新打包,下的就是 CfT 原样的 zip —— 没有第二层要记 |
| **channel(装系统 `.deb`)** | **不抄** | 我们已经有 `--browser <路径>`,显式指过去就行;再造一条"帮你 apt install"要 root,而且钉不住版本(§1) |
| **arm64 自己 build** | **不抄** | 要养构建流水线,那是比"不发镜像"重得多的承诺(§3) |
| **多浏览器 / ffmpeg / winldd** | **不抄** | 我们只要一个 Chromium;`ffmpeg` 那条以后真要录像再说 |
| **默认装中文字体** | ~~不抄~~ → **0.7.0 抄了** | 原来的理由是"我们不碰系统的包管理器,`--with-deps` 才动手"。**这条翻了**:`install` 的职责就是跑之前把环境弄好,探到缺了却不装等于把活原样退回去。现在有 root 就装(字体、chrome 的共享库、xpra 那三样),**没 root 才退化成打印** —— 那时候我们确实做不了,而不是选择不做。包名和发行版差异在 [deps.py](../../../webmuxd/cli/deps.py) |

前两条**已经修了**(写这篇时顺手验出来的 —— 那条"看起来像装好了"不是推理,
是实测出来的)。剩下三条还欠着:`apt-get install -s`、失败轮转、目录锁。

带来一个迁移代价:**0.5.1 及更早装的浏览器没有标记文件,升级后会重下一次。**
150 MB 不能静默发生,所以 `install` 会先说一句
「装了一半或是旧版本装的,重下一次」再动手。

## 8. ↔ 别处

| | |
| --- | --- |
| 我们的 install 长什么样 | [07 §4](07-runtime.md#4-webmuxd-install-下一个浏览器) |
| 为什么钉死版本 | [07 §4.1](07-runtime.md#41-钉死版本这是重点) |
| 下载源怎么挑 | [07 §4.2](07-runtime.md#42-下什么从哪下) |
| 依赖和字体 | [07 §4.3](07-runtime.md#43-系统依赖和字体照抄-playwright-的姿态) |
| 记录文件的规矩 | [v1/cli/install.md](../../v1/cli/install.md) —— 原样继承 |
