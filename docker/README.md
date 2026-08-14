# 镜像 · 怎么用

webmuxd 需要两个端点:**一扇窗**给人、**一个 CDP** 给代码
([works/08](../docs/v1/works/08-browser-runtime.md))。现成的浏览器镜像都做好了第一个,
第二个几乎都没有。这里的两个镜像就是把第二个补上。

| 镜像 | 底座 | 挑它的理由 |
| --- | --- | --- |
| `ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0` | `kasmweb/chromium` | **画面最好** |
| `ghcr.io/memory-co/webmuxd/jlesage-chromium:v26.08.1` | `jlesage/chromium` | **`--network host` 下能一机多开** |

各自的技术细节和代价在自己的目录里:
[kasmweb-chromium/](kasmweb-chromium/README.md) · [jlesage-chromium/](jlesage-chromium/README.md)

## 拉

```bash
docker pull ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0
docker pull ghcr.io/memory-co/webmuxd/jlesage-chromium:v26.08.1
```

**tag 跟着底座走,不用 `latest`** —— 底座换版本 = 换一个镜像,不是同一个东西
变了。想知道自己跑的是哪一版,`docker inspect` 看 tag 就够。

自己 build 也行,一个镜像一个目录,构建上下文就是那个目录:

```bash
docker build -t ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0 docker/kasmweb-chromium/
docker build -t ghcr.io/memory-co/webmuxd/jlesage-chromium:v26.08.1 docker/jlesage-chromium/
```

换底座版本用 `--build-arg BASE=...`(记得把 tag 也跟着改)。

`webmuxd install` 只探测 `default_container` 在不在本机或拉得到,**它不 build**
([cli/install.md](../docs/v1/cli/install.md))。

## 端口:两个镜像同一套名字

两个底座各有各的变量名(`NO_VNC_PORT` / `WEB_LISTENING_PORT`、
`APP_ARGS` / `CHROMIUM_CUSTOM_ARGS`……)。**wrapper 把它们翻译掉了**,
对外只有两个:

| | 是什么 | 默认 |
| --- | --- | --- |
| `WEBMUXD_WINDOW_PORT` | 窗听在哪个口 —— 人用浏览器开的那个 | 底座各自的(6901 / 5800) |
| `WEBMUXD_CDP_PORT` | CDP 听在哪个口 —— webmuxd 连的那个 | `9222` |

```bash
docker run -d --shm-size=1g --network host \
  -e WEBMUXD_WINDOW_PORT=8090 -e WEBMUXD_CDP_PORT=9222 \
  -e VNC_PW=至少六位 \
  ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0

docker run -d --shm-size=1g --network host \
  -e WEBMUXD_WINDOW_PORT=8091 -e WEBMUXD_CDP_PORT=9333 \
  ghcr.io/memory-co/webmuxd/jlesage-chromium:v26.08.1
```

**换镜像不用改这两行。** 这也是 webmuxd 自己驱动它们的方式 —— 它读镜像标签
拿到变量名,所以加第三个镜像不用改代码(见下)。

> `WEBMUXD_CDP_PORT + 1` 是 Chromium 在容器里实际听的口(两个底座都这样)。
> 挑口时别让它和窗口的口挨着。

用 `bridge` 的话就不用管这两个了,直接 `-p` 映射底座的默认口:

```bash
docker run -d --shm-size=1g \
  -p 127.0.0.1:8090:6901 -p 127.0.0.1:9222:9222 \
  -e VNC_PW=至少六位 ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0
```

## 谁能一机多开

`--network host` 是 webmuxd 的默认跑法(这样容器里的 `localhost` 就是你的
`localhost`,调试本机页面用得上)。它带来一条限制:

| | `--network host`(默认) | `--network bridge` |
| --- | --- | --- |
| **kasmweb** | **一台机器一个** | 想开几个开几个 |
| **jlesage** | 想开几个开几个 | 想开几个开几个 |
| 容器里的 `localhost` | **就是你的** | 是它自己的 |
| 网络隔离 | 没有 | 有 |

怎么选:**画面最好又只开一个 → kasmweb + host**(默认);**要同时跑好几个又想要
那个 `localhost` → jlesage + host**;**要网络隔离 → 加 `--network bridge`**,
代价是够不着你机器上只绑 loopback 的服务。

原因在 [kasmweb-chromium/README](kasmweb-chromium/README.md#-network-host-下一台机器只能跑一个)
—— 一句话:KasmVNC 的内部会合点用**容器内 PID** 命名,而那个名字归 netns 管。

## 标签:让 webmuxd 知道这镜像长什么样

每个镜像把自己的 profile 写在 `webmuxd.*` 标签里,`docker inspect` 就能读到 ——
**加一个新镜像不用改 webmuxd 的代码**:

```bash
docker inspect -f '{{json .Config.Labels}}' ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0 | jq
```

| 标签 | 意思 |
| --- | --- |
| `webmuxd.window.port` / `.scheme` | 窗在哪个口、什么协议 |
| `webmuxd.window.port_env` | 改窗口端口的变量名(两个都是 `WEBMUXD_WINDOW_PORT`) |
| `webmuxd.window.user` / `.user_env` | 登录名写死的还是变量定的 |
| `webmuxd.window.password_env` | 口令从哪个变量来 |
| `webmuxd.cdp.port` / `.port_env` | CDP 默认口、改它的变量名 |
| `webmuxd.chromium.args_env` / `.url_env` | 往 Chromium 塞参数 / 给启动页的变量名(空 = 没有这个概念) |
| `webmuxd.host_network` | `multi` = 能一机多开;`single` = host 下只能一个 |

## 加第三个镜像

1. 新目录 `docker/<出处>-<应用>/`,Dockerfile、entrypoint、README 都放里面
2. entrypoint 把 `WEBMUXD_WINDOW_PORT` / `WEBMUXD_CDP_PORT` **翻译成底座认的名字**
3. CDP:底座自带转发就打开它,没有就补一个(抄
   [`cdp-relay.py`](kasmweb-chromium/cdp-relay.py),只依赖镜像里有 `python3`)
4. 把标签填全
5. 写 README:**它的代价是什么、能不能一机多开**

接之前先量三件事,都在现场咬过人:

- **参数是不是真进去了。** 别信变量名,`docker exec … cat /proc/net/tcp` 看
  `0100007F:2406` 在不在。写错的变量 docker 会照收,然后**静默忽略**
- **有没有用带名字的抽象 socket。** `grep -oE '@[^ ]+' /proc/net/unix` ——
  这决定它能不能共享 netns(要在 **bridge** 下看,host 下你看到的是宿主机那份)
- **启动脚本假设了什么。** kasm 死等一张叫 `eth*` 的网卡,换个网络模式就死循环,
  而症状是"容器 Up、日志停住、没有任何报错"

## 另外那个目录

`dev/` 和这两个无关 —— 跑测试用的(alpine-chrome + python),见 [QUICKSTART](../QUICKSTART.md)。
