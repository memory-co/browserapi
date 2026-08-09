# 开发用镜像:Chromium + Python,跑在同一个容器里。
#
# 为什么不从宿主连 CDP:Chromium 的 Host 头校验挡掉容器外访问
# (docs/v1/works/01-container.md §3 的实测记录)。所以引擎的开发和测试
# 必须在容器内跑 —— 这也正是 sessiond 跑在容器里的原因。
#
# 生产镜像是 kasmweb/chromium(带 VNC 和桌面),这里只要引擎能跑,用轻的。
FROM zenika/alpine-chrome:latest

USER root
RUN apk add --no-cache python3 py3-pip \
 && python3 -m venv /venv \
 && /venv/bin/pip install --no-cache-dir websockets aiohttp pytest pytest-asyncio
ENV PATH="/venv/bin:$PATH" PYTHONPATH=/src PYTHONDONTWRITEBYTECODE=1
WORKDIR /src
ENTRYPOINT []
CMD ["sh"]
