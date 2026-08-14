#!/bin/sh
# 把统一的 WEBMUXD_* 变量翻译成这个底座认的名字,然后原样交回去。
# 为什么两个镜像要用同一套名字,见 ../README.md。
set -e

export WEB_LISTENING_PORT="${WEBMUXD_WINDOW_PORT:-5800}"
export CHROMIUM_REMOTE_DEBUGGING_PORT="${WEBMUXD_CDP_PORT:-9222}"

if [ -n "${WEBMUXD_PASSWORD:-}" ]; then
    export WEB_AUTHENTICATION=1
    export WEB_AUTHENTICATION_USERNAME="${WEBMUXD_USER:-webmuxd}"
    export WEB_AUTHENTICATION_PASSWORD="$WEBMUXD_PASSWORD"
    # **底座要求认证必须配 https,否则启动就退出**,而报的错在一堆 cont-init
    # 日志中间,不看到底翻不出来。既然口令是我们要求的,这个就替调用方开掉。
    export SECURE_CONNECTION=1
fi

exec /init "$@"
