# 更新日志

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
