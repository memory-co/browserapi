# 把 jlesage/chromium 改造成 webmuxd 能用的镜像:底座本来就有 CDP
# 转发,这一层只是默认打开它、并统一端口变量名。见 ./README.md。
ARG BASE=jlesage/chromium:latest
FROM ${BASE}

COPY entrypoint.sh /usr/local/bin/webmuxd-entrypoint
RUN chmod 755 /usr/local/bin/webmuxd-entrypoint

# 默认打开底座自带的 CDP 转发。端口沿用它自己的变量名,理由见 entrypoint。
ENV CHROMIUM_REMOTE_DEBUGGING=1
EXPOSE 5800 9222

LABEL webmuxd.window.port=5800 \
      webmuxd.window.scheme=http \
      webmuxd.window.user_env=WEB_AUTHENTICATION_USERNAME \
      webmuxd.window.password_env=WEB_AUTHENTICATION_PASSWORD \
      webmuxd.window.port_env=WEBMUXD_WINDOW_PORT \
      webmuxd.cdp.port=9222 \
      webmuxd.cdp.port_env=WEBMUXD_CDP_PORT \
      webmuxd.chromium.args_env=CHROMIUM_CUSTOM_ARGS \
      webmuxd.chromium.url_env="" \
      webmuxd.host_network=multi

ENTRYPOINT ["/usr/local/bin/webmuxd-entrypoint"]
