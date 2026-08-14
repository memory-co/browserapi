# 更新日志

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
