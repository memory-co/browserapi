# 把 jlesage/chromium 改造成 webmuxd 能用的镜像:底座本来就有 CDP
# 转发,这一层只是默认打开它、并统一端口变量名。见 ./README.md。
ARG BASE=jlesage/chromium:v26.08.1
FROM ${BASE}

COPY entrypoint.sh /usr/local/bin/webmuxd-entrypoint
RUN chmod 755 /usr/local/bin/webmuxd-entrypoint

# 默认打开底座自带的 CDP 转发。端口沿用它自己的变量名,理由见 entrypoint。
# 画面固定走 https(自签名)。**不能让它随鉴权开关变** —— 标签里写死了
# `window.scheme=https`,而标签是调用方据以拼 URL 的事实,不能有时对有时错。
ENV CHROMIUM_REMOTE_DEBUGGING=1 \
    SECURE_CONNECTION=1
EXPOSE 5800 9222

LABEL webmuxd.window.port=5800 \
      webmuxd.window.scheme=https \
      webmuxd.window.user_env=WEBMUXD_USER \
      webmuxd.window.password_env=WEBMUXD_PASSWORD \
      webmuxd.window.port_env=WEBMUXD_WINDOW_PORT \
      webmuxd.window.bind_env=WEBMUXD_BIND \
      webmuxd.window.auth_env=WEBMUXD_AUTH \
      webmuxd.window.tls_env=WEBMUXD_TLS \
      webmuxd.cdp.port=9222 \
      webmuxd.cdp.port_env=WEBMUXD_CDP_PORT \
      webmuxd.chromium.args_env=CHROMIUM_CUSTOM_ARGS \
      webmuxd.chromium.url_env="" \
      webmuxd.host_network=multi

ENTRYPOINT ["/usr/local/bin/webmuxd-entrypoint"]
