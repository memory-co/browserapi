#!/usr/bin/env bash
# 把统一的 WEBMUXD_* 变量翻译成这个底座认的名字,起中继,然后把 kasm 原本的
# 启动链原样 exec 回去。为什么要中继、为什么要翻译,见 ./README.md。
set -e

export NO_VNC_PORT="${WEBMUXD_VIEW_PORT:-6901}"
# 窗绑哪个地址。底座把 `-interface 0.0.0.0` 写死在启动脚本里,我们在 build
# 时把它 patch 成了变量(见 Dockerfile)。
export KASM_INTERFACE="${WEBMUXD_BIND:-0.0.0.0}"
# 桌面分辨率。**要和浏览器窗口一致**,否则窗口比桌面大会被裁、比桌面小会留白,
# 而"人看到的画面和截图是同一个"正是这东西的全部意义。
if [ -n "${WEBMUXD_WINDOW_SIZE:-}" ]; then
    export VNC_RESOLUTION="$WEBMUXD_WINDOW_SIZE"
fi
# 画面口令。**用户名 kasm_user 是 KasmVNC 写死的**,这个镜像改不了。
#
# 写成 if,不写 `[ -n … ] && export …` —— 后者在不给口令时返回非零,
# 配上 `set -e` 会**直接把容器杀掉**,而日志里什么线索都没有。
if [ -n "${WEBMUXD_PASSWORD:-}" ]; then
    export VNC_PW="$WEBMUXD_PASSWORD"
fi

# 关掉鉴权。KasmVNC 的参数叫 `-DisableBasicAuth`(BoolParameter,默认 false)。
# **追加到 VNCOPTIONS,不覆盖** —— 底座在那儿放了画质相关的一串默认值。
case "${WEBMUXD_AUTH:-1}" in
    0|false|no) export VNCOPTIONS="${VNCOPTIONS:-} -DisableBasicAuth" ;;
esac

CDP_PORT="${WEBMUXD_CDP_PORT:-9222}"
INNER=$((CDP_PORT + 1))          # Chromium 只肯听 127.0.0.1,它在里面那个口

# 调用方给了 APP_ARGS 就追加,没给就补上 kasm 自己的默认值 —— **不能直接覆盖**:
# 它是 ARGS=${APP_ARGS:-$DEFAULT_ARGS},我们一设,它的默认值就整个没了。
export APP_ARGS="${APP_ARGS:---start-maximized} --remote-debugging-port=${INNER}"

python3 /usr/local/bin/cdp-relay.py "$CDP_PORT" "$INNER" &

exec /dockerstartup/kasm_default_profile.sh \
     /dockerstartup/vnc_startup.sh \
     /dockerstartup/kasm_startup.sh "$@"
