#!/bin/sh
# 把统一的 WEBMUXD_* 变量翻译成这个底座认的名字,然后原样交回去。
# 为什么两个镜像要用同一套名字,见 ../README.md。
set -e

export WEB_LISTENING_PORT="${WEBMUXD_VIEW_PORT:-5800}"
export CHROMIUM_REMOTE_DEBUGGING_PORT="${WEBMUXD_CDP_PORT:-9222}"

# 桌面分辨率。底座分成宽高两个变量,这里把 WxH 拆开。
if [ -n "${WEBMUXD_WINDOW_SIZE:-}" ]; then
    export DISPLAY_WIDTH="${WEBMUXD_WINDOW_SIZE%x*}"
    export DISPLAY_HEIGHT="${WEBMUXD_WINDOW_SIZE#*x}"
fi

# 窗绑哪个地址。底座只给了个布尔(只听 loopback 与否),所以这里把地址翻译成
# 布尔 —— 它表达不了"绑某个具体网卡",而我们也只需要这两种。
case "${WEBMUXD_BIND:-0.0.0.0}" in
    127.0.0.1|localhost|::1) export WEB_LOCALHOST_ONLY=1 ;;
    *)                       export WEB_LOCALHOST_ONLY=0 ;;
esac

# 画面走 https 还是 http。**只有这个底座能切** —— kasm 那边 KasmVNC 恒 TLS,
# 拿掉 -sslOnly 也一样(实测),所以那个镜像不声明这个能力。
case "${WEBMUXD_TLS:-1}" in
    0|false|no) export SECURE_CONNECTION=0 ;;
    *)          export SECURE_CONNECTION=1 ;;
esac

case "${WEBMUXD_AUTH:-1}" in
    0|false|no) WEBMUXD_PASSWORD="" ;;      # 关掉鉴权 = 不设口令,底座默认就不开
esac

if [ -n "${WEBMUXD_PASSWORD:-}" ]; then
    export WEB_AUTHENTICATION=1
    export WEB_AUTHENTICATION_USERNAME="${WEBMUXD_LOGIN:-webmuxd}"
    export WEB_AUTHENTICATION_PASSWORD="$WEBMUXD_PASSWORD"
    # 底座默认拒绝"要口令又不走 https"(凭据会明文传)。既然两个开关都是
    # 调用方显式选的,这里放行它自己的逃生阀,并让它自己打那段警告。
    [ "${SECURE_CONNECTION:-1}" = "0" ] && export WEB_AUTHENTICATION_ALLOW_INSECURE=1
fi
# SECURE_CONNECTION 在 Dockerfile 里就固定开着 —— 底座要求"开认证必须走 https"
# (否则启动直接退出,报错埋在一堆 cont-init 日志里),而且关掉鉴权时也不能让
# scheme 变回 http:标签写死了 https,它得一直是真的。

exec /init "$@"
