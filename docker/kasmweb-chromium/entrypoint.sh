#!/usr/bin/env bash
# 把统一的 WEBMUXD_* 端口名翻译成这个底座认的名字,起中继,然后把 kasm 原本的
# 启动链原样 exec 回去。为什么要中继、为什么要翻译,见 ./README.md。
set -e

export NO_VNC_PORT="${WEBMUXD_WINDOW_PORT:-6901}"
CDP_PORT="${WEBMUXD_CDP_PORT:-9222}"
INNER=$((CDP_PORT + 1))          # Chromium 只肯听 127.0.0.1,它在里面那个口

# 调用方给了 APP_ARGS 就追加,没给就补上 kasm 自己的默认值 —— **不能直接覆盖**:
# 它是 ARGS=${APP_ARGS:-$DEFAULT_ARGS},我们一设,它的默认值就整个没了。
export APP_ARGS="${APP_ARGS:---start-maximized} --remote-debugging-port=${INNER}"

python3 /usr/local/bin/cdp-relay.py "$CDP_PORT" "$INNER" &

exec /dockerstartup/kasm_default_profile.sh \
     /dockerstartup/vnc_startup.sh \
     /dockerstartup/kasm_startup.sh "$@"
