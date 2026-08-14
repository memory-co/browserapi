#!/bin/sh
# 把统一的 WEBMUXD_* 端口名翻译成这个底座认的名字,然后原样交回去。
# 为什么两个镜像要用同一套名字,见 ../README.md。
set -e

export WEB_LISTENING_PORT="${WEBMUXD_WINDOW_PORT:-5800}"
export CHROMIUM_REMOTE_DEBUGGING_PORT="${WEBMUXD_CDP_PORT:-9222}"

exec /init "$@"
