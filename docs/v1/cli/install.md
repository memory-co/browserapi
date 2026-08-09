# CLI · `webmuxd install`

**探一遍,写下来,别再问。**

```bash
webmuxd install
```

## 1. 它只回答两个问题

1. **docker 能用吗**
2. **这个网络环境拉得到那个镜像吗**

就这两条。

```console
$ webmuxd install
探测环境…
  python      3.11.2                             ✓
  docker      29.7.2                             ✓
  镜像          kasmweb/chromium:1.18.0            ✓

记录写到 ~/.webmuxd.json
```

**它不 build 任何东西,也不预先 `docker pull`。** 镜像是 kasm 原厂的,
`docker run` 自己会拉;这里只用 `docker manifest inspect` 问一下拉不拉得到
(一秒,不下 4 GB)—— 免得你在起 session 的时候才发现到不了 registry。

**它是幂等的。** 再跑一次就是重新探一遍,所以"检查"和"安装"是同一个命令,
不需要单独的 `doctor`。

## 2. 拉不到镜像时,键就不写

```console
$ webmuxd install
探测环境…
  python      3.11.2                             ✓
  docker      29.7.2                             ✓
  镜像          kasmweb/chromium:1.18.0 拉不到      ⚠
     这个网络环境到不了 registry。自己指一个:webmuxd new --image <你的镜像>

记录写到 ~/.webmuxd.json
⚠ 没有 default_container —— container runtime 得每次指定 --image
```

**不记一个拉不下来的名字。** 记录里键不在,就是"你得自己填" ——
留个探不到的值,等于骗后面的自己。

## 3. 记录长什么样

```json
{
  "version": 1,
  "at": "2026-08-09T00:18:24Z",
  "docker": "/usr/bin/docker",
  "docker_version": "29.7.2",
  "default_container": "kasmweb/chromium:1.18.0"
}
```

**键在 = 探到了,键不在 = 没探到。** 就这一条规矩,没有 `ok: false` 这种
带着理由的空壳。

`version` 是**记录格式**的版本。格式变了老记录读不动,那就当没有记录 ——
重新探,而不是猜字段。

**它不是配置文件。** 记的是机器的事实,不是你的选择:webmuxd 没有配置文件,
参数从 lib 传([README §5](README.md#5-没有配置文件))。
`default_container` 是"这台机器够得到哪个镜像",而**你想用哪个**永远是
`session(image=...)` / `--image` 说了算 —— 传进来的赢。

## 4. 记录过期了怎么办

**记录会撒谎** —— 你 `docker rmi` 了镜像,文件不会自己更新。所以规矩是:

- **信记录,但别替它兜底。** 用记录里的值直接去起;起不来就报错,
  **并且在提示里说"跑 `webmuxd install` 重新探一遍"**。
- **不静默重探。** 每次都重探等于这个命令白做;而"有时候重探有时候不"更糟 ——
  你就不知道自己看到的是什么时候的事实。

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
