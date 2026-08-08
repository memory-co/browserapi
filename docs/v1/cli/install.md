# CLI · `webmuxd install`

**装一次,之后别再问。**

```bash
webmuxd install
```

探一遍环境、把该装的装上、把结果写进 `~/.webmuxd.json`。
之后所有命令读那份记录,不再每次去 `docker info` 一遍。

## 1. 它不是配置文件

`~/.webmuxd.json` 记的是**机器的事实** —— docker 通不通、chromium 在哪、镜像拉没拉。
**不是你的选择**:webmuxd 没有配置文件,参数从 lib 传
([README §5](README.md#5-没有配置文件))。

**别手写它。** 手改一份探测记录,等于骗后面的自己 —— 你会得到一个
"记录说有、实际没有"的环境,而那正是 §4 要处理的坏情况。

## 2. 它做什么

```console
$ webmuxd install
探测环境…
  python      3.11.2                                    ✓
  docker      29.7.2                                    ✓
拉底座 kasmweb/chromium:1.18.0 …(4 GB 左右,第一次会久)
build webmuxd/kasm-chromium:0.1.0 …(在底座上加 python + webmuxd)
  ✓ 镜像就绪
  chromium    找不到                                     ⚠ process runtime 用不了

可用的 runtime:container  remote
默认:container
记录写到 ~/.webmuxd.json
```

**它是幂等的。** 再跑一次就是重新探一遍 —— 所以"检查"和"安装"是同一个命令,
不需要单独的 `doctor`。**镜像已经在本机就直接跳过**,不重复拉也不重复 build。

**加料层是本机 build 的,不从 registry 拉。** 底座 `kasmweb/chromium` 是 kasm 官方的,
我们只在上面加 python + 一个钉死版本的 webmuxd([works/01 §3](../works/01-container.md#3-镜像))
—— 两条 RUN,不值得为它维护一个仓库。

**探不到的东西不让整条命令失败。** docker 不通就把 `container` 记成不可用**并写下原因**,
剩下的照常。一个能用 `process` 的机器不该因为没装 docker 就装不上。

## 3. 记录长什么样

```jsonc
{
  "version": 1,
  "at": "2026-08-08T21:40:12Z",
  "webmuxd": "0.1.0",
  "runtimes": {
    "container": { "ok": true,  "docker": "/usr/bin/docker",
                   "base_image": "kasmweb/chromium:1.18.0",
                   "image": "webmuxd/kasm-chromium:0.1.0", "image_pulled": true },
    "process":   { "ok": true,  "chromium": "/usr/bin/chromium-browser",
                   "vnc": null,
                   "notes": ["没有 Xvnc —— 这种 session 只有 API 没有画面"] },
    "remote":    { "ok": true }
  },
  "default_runtime": "container"
}
```

`version` 是**记录格式**的版本。格式变了老记录读不动,那就当没有记录 ——
重新探一遍,而不是猜字段。

## 4. 记录过期了怎么办

**记录会撒谎** —— 你 `docker rm` 了镜像、卸了 chromium,文件不会自己更新。
所以规矩是:

- **信记录,但别替它兜底。** 用记录里的路径直接去起;起不来就报错,
  **并且在提示里说"跑 `webmuxd install` 重新探一遍"**。
- **不静默重探。** 每次都重探等于这个命令白做;而"有时候重探有时候不"更糟 ——
  你就不知道自己看到的是什么时候的事实。

```console
$ webmuxd new -s work -p 7900
✗ runtime_unavailable: 记录里说 chromium 在 /usr/bin/chromium-browser,但它不在了
  跑一下 webmuxd install 重新探
```

## 5. 没装过也能用

**`~/.webmuxd.json` 不存在时,一切照常** —— 该探还是探,只是每次都探。
`install` 省的是**重复的开销和不确定性**,不是"必须先装"。

写脚本的人尤其不该被它挡住:`Webmuxd()` 在库里直接用,不要求先跑过 CLI。

## 6. ↔ 别处

| | |
| --- | --- |
| `webmuxd info` | 显示记录里的内容 + 记录是什么时候的 |
| `runtime.detect()` | 有记录读记录,没记录现探([works/05 §4](../works/05-server-session-runtime.md#4-runtime--唯一多出来的概念)) |
| 参数怎么给 | 从 lib 传,或命令行 flag —— 没有配置文件([README §5](README.md#5-没有配置文件)) |
