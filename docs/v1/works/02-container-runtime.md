# 02 · 容器运行时:kasm/chrome 基座改造

## 1. 基线假设(实现前需按锁定 tag 复核)

以 `kasmweb/chrome` 为基础镜像。以下是设计时依赖的性质,**均需在实现时对锁定的镜像 tag 实测确认**,
因为 kasm 镜像的启动脚本与环境变量在版本间有过变化:

| 假设 | 说明 | 若不成立的应对 |
| --- | --- | --- |
| A1 | 容器内以 KasmVNC 提供 web 原生远程桌面,默认 HTTPS 端口 `6901` | 端口可配置化,不硬编码 |
| A2 | 存在启动钩子(`/dockerstartup/custom_startup.sh` 一类),可覆盖应用启动命令 | 退化为直接覆盖 `ENTRYPOINT`,自行拉起 Xvnc 与 Chrome |
| A3 | 应用以非 root 用户(`kasm_user`,uid 1000)运行 | 按实际 uid 调整文件属主 |
| A4 | VNC 访问凭据可由环境变量注入(`VNC_PW` 一类) | 改为启动时写入密码文件 |
| A5 | 可通过环境变量关闭不需要的周边服务(音频、上传、打印) | 在启动脚本里显式不拉起 |

> 这些假设集中写在这里,是为了让"镜像升级"变成一次**只读这一节**的复核动作,而不是全仓库 grep。

## 2. 镜像构建

```dockerfile
# Dockerfile.operator  (设计示意)
ARG KASM_CHROME_TAG=1.16.0        # 显式锁定,不用 latest
FROM kasmweb/chrome:${KASM_CHROME_TAG}

USER root

# 1) agentd 运行时(独立 venv,不污染镜像自带 python)
COPY --chown=1000:1000 dist/agentd /opt/browserapi/agentd
RUN /opt/browserapi/agentd/bin/pip install --no-cache-dir -r /opt/browserapi/agentd/requirements.txt

# 2) 启动钩子:接管 Chrome 的拉起方式
COPY --chown=1000:1000 runtime/custom_startup.sh /dockerstartup/custom_startup.sh
COPY --chown=1000:1000 runtime/chrome_flags.conf /opt/browserapi/chrome_flags.conf
RUN chmod +x /dockerstartup/custom_startup.sh

# 3) 健康检查与轨迹暂存目录
RUN mkdir -p /var/lib/browserapi/{profile,spool,downloads} && chown -R 1000:1000 /var/lib/browserapi

USER 1000
EXPOSE 6901 7070
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s \
  CMD curl -fsS http://127.0.0.1:7070/healthz || exit 1
```

端口约定:

| 端口 | 用途 | 暴露范围 |
| --- | --- | --- |
| `6901` | KasmVNC(人观看/接管) | 经 Ingress,一次性 token 鉴权 |
| `7070` | agentd 控制接口(HTTP + WS) | **仅控制面可达**,不对外 |
| `9222` | Chrome CDP | **仅 `127.0.0.1`**,永不出容器 |

## 3. Chrome 启动参数

```bash
# runtime/custom_startup.sh (设计示意,关键部分)
CHROME_FLAGS=(
  --remote-debugging-port=9222
  --remote-debugging-address=127.0.0.1     # 关键:CDP 锁在 loopback
  --remote-allow-origins=http://127.0.0.1:9222
  --user-data-dir=/var/lib/browserapi/profile
  --window-position=0,0
  --window-size=${BAPI_VIEWPORT_W:-1280},${BAPI_VIEWPORT_H:-800}
  --disable-session-crashed-bubble         # 崩溃恢复气泡会挡住页面,污染观测
  --disable-infobars
  --no-first-run --no-default-browser-check
  --password-store=basic                   # 避免 keyring 弹窗阻塞
  --disable-features=Translate,MediaRouter  # 减少非预期 UI
)
[ -n "$BAPI_PROXY" ] && CHROME_FLAGS+=(--proxy-server="$BAPI_PROXY")

# agentd 先起,它负责在 Chrome ready 后建立 CDP 连接并对外声明 healthy
/opt/browserapi/agentd/bin/python -m agentd --port 7070 &
exec /opt/google/chrome/chrome "${CHROME_FLAGS[@]}" "about:blank"
```

**刻意不加的参数**:`--headless`(要 GUI 才能被看见)、`--no-sandbox`
(应保留 Chrome 沙箱;若基础镜像因容器权限限制必须关闭,需在 [07](07-security-and-ops.md) 记为已知风险并用 seccomp 补偿)、
以及各类反检测 flag(非目标)。

**窗口尺寸与视口**:headful 下 CDP 的 `Emulation.setDeviceMetricsOverride` 会让截图与真实屏幕内容不一致,
从而破坏"人看到的"与"Agent 看到的"是同一画面这一前提。因此 **v1 通过 X 显示分辨率 + 窗口尺寸控制视口,不用 emulation override**。
改视口 = 改会话配置 = 重设 Xvnc 分辨率并重排窗口。

## 4. agentd

容器内唯一的控制进程,是整个系统的执行核心。

### 4.1 职责
1. **CDP 会话管理**:连接 `127.0.0.1:9222`,维护 target/tab 集合,处理 target 增删与崩溃重连。
2. **动作执行**:把协议动作([03](03-action-protocol.md))翻译成 CDP 调用,含定位、可见性/可点击性等待、执行、稳定性等待。
3. **观测生成**:AX 树 + 布局 → 元素表 → 标注截图。
4. **效果采集**:常驻订阅 `Page` / `Network` / `Runtime` / `Log` / `DOM` 域事件,按动作时间窗归集成 Effect。
5. **事件外发**:通过 WS 向控制面推送会话事件(见 [04](04-trajectory-model.md) §5)。
6. **接管仲裁**:持有 `control_mode`,在 human 模式下拒绝 Agent 动作,并采集人操作产生的页面变化。
7. **本地暂存**:控制面短暂不可达时,事件与 blob 落 `/var/lib/browserapi/spool` 并重放,避免轨迹断片。

### 4.2 实现选型
底层用 **Playwright 的 `connect_over_cdp()`** 而非裸 CDP:
它已经把"等待元素可见/可点击/网络空闲/frame 处理/文件上传"这些脏活做对了,自研成本高且容易错。
但这是**实现细节,不进协议**——协议层只暴露 browserapi 自己的动作语义,
以便未来在不改调用方代码的前提下换底层(见 ADR-002)。

### 4.3 内部结构
```
agentd/
├── server.py          # HTTP(动作/观测) + WS(事件)
├── cdp/               # 连接管理、target 跟踪、崩溃恢复
├── perception/
│   ├── ax.py          # AX 树抓取与可交互元素过滤
│   ├── signature.py   # 元素稳定签名
│   ├── annotate.py    # Set-of-Mark 截图标注
│   └── redact.py      # 脱敏
├── actions/           # 每个动作一个 handler,统一 pre/post 钩子
├── effects/           # 事件订阅、时间窗归集、DOM diff
├── takeover.py        # control_mode 仲裁 + 人操作采集
└── spool.py           # 断连暂存与重放
```

### 4.4 动作执行的统一时序
每个动作 handler 都跑在同一个包裹里,保证轨迹字段齐整:

```
1. precondition   目标可解析?control_mode 允许?policy 准入?
2. pre_snapshot   url / title / scroll / (可选)动作前截图
3. mark_begin     开启效果采集时间窗,记 t0
4. dispatch       实际 CDP 调用
5. settle         等待稳定:网络静默 或 DOM 静默 或 超时(三者取先到,阈值可配)
6. post_snapshot  url / title / 动作后截图 / DOM diff 摘要
7. collect        关闭时间窗,归集 network/console/dialog/download/navigation
8. emit           action.result 事件 + 返回值
```

`settle` 的策略很关键:等太短会拍到过渡态(轨迹里全是加载中的白屏,回放没法看),
等太长则整体吞吐塌陷。v1 默认:**DOM 静默 300ms 且 网络在飞请求数为 0,上限 5s**,可按动作类型覆盖。

## 5. 会话内的状态

| 状态 | 存放位置 | 是否跨会话保留 |
| --- | --- | --- |
| Cookie / localStorage | `--user-data-dir` profile 卷 | 可选:绑定 `profile_id` 则挂载持久卷 |
| 下载文件 | `/var/lib/browserapi/downloads` | 通过 API 取回;容器销毁即失 |
| 上传文件 | 由控制面推入容器指定目录 | 否 |
| 轨迹 blob | `spool` → 上传对象存储 | 是(容器销毁后仍在) |

**profile 复用**是登录态复用的关键:`profile_id` 相同的会话挂同一个持久卷,
但同一 profile **同一时刻只允许一个活跃会话**(Chrome profile 不支持并发),由 Session Manager 加锁。

## 6. 生命周期

```
requested → provisioning → ready → active ⇄ idle → draining → terminated
                  │                  │                  │
                  └──► failed        └──► unhealthy ────┘
```

| 迁移 | 触发 |
| --- | --- |
| `provisioning → ready` | HEALTHCHECK 通过 且 agentd 报告 CDP 已连接 |
| `ready → active` | 首次动作或首次 run 开始 |
| `active → idle` | 无动作超过 `idle_soft`(默认 5 min) |
| `idle → draining` | 超过 `idle_hard`(默认 30 min)或被驱逐 |
| `draining → terminated` | spool 刷完、下载文件已归档、profile 卷解锁 |
| `* → unhealthy` | 心跳丢失 / Chrome 崩溃且重连失败 |

**销毁前必须完成 spool flush**,否则最后几步轨迹丢失——而失败任务的最后几步恰恰是最需要看的。
因此 `draining` 是一个显式状态,不是直接 kill。
