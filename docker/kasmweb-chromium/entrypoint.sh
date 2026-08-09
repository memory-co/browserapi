#!/usr/bin/env bash
# webmuxd wrapper —— 在 kasm 原本的启动链前面做两件事,然后原样交回去。
#
#   1. 把 --remote-debugging-port 拼进 APP_ARGS(kasm 注入 Chromium 参数的口子)
#   2. 起一个中继,把那个口搬到 0.0.0.0:$WEBMUXD_CDP_PORT
#
# **不改 kasm 的任何脚本。** 它的入口原样 exec 回去,行为和原厂一致。
set -e

CDP_PORT="${WEBMUXD_CDP_PORT:-9222}"
INNER=$((CDP_PORT + 1))          # Chromium 只肯听 127.0.0.1,所以它在里面那个口

# 调用方给了 APP_ARGS 就在后面追加,没给就补上 kasm 自己的默认值 ——
# **不能直接覆盖**:kasm 的 custom_startup.sh 是 ARGS=${APP_ARGS:-$DEFAULT_ARGS},
# 我们一设,它的默认值就整个没了。
export APP_ARGS="${APP_ARGS:---start-maximized} --remote-debugging-port=${INNER}"

python3 /usr/local/bin/cdp-relay.py "$CDP_PORT" "$INNER" &

exec /dockerstartup/kasm_default_profile.sh \
     /dockerstartup/vnc_startup.sh \
     /dockerstartup/kasm_startup.sh "$@"
