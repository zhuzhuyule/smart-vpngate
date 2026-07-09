# Smart VPNGate 多出口 —— 容器镜像
# 纯标准库 Python + openvpn/iproute2/curl，无 pip 依赖。
FROM python:3.12-slim

# 运行时系统依赖（与 install.sh 一致）：openvpn 隧道、iproute2 策略路由、
# curl 出口检测、psmisc/procps 进程管理、iptables 本机诊断。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openvpn iproute2 curl ca-certificates iptables psmisc procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY vpngate_manager.py proxy_server.py vpn_utils.py ./

# 数据目录用环境变量驱动（挂 volume 持久化 ui_auth.json / nodes.json 等）。
# LOCAL_PROXY_HOST=:: 使代理监听所有接口 —— 桥接端口映射与本机 127.0.0.1 均可用。
# UI_HOST=:: 网页管理监听所有接口。
# EXIT_COUNT 为首次启动的默认出口数量（可在网页里 1~10 之间再改）。
ENV VPNGATE_DATA_DIR=/app/vpngate_data \
    LOCAL_PROXY_HOST=:: \
    UI_HOST=:: \
    EXIT_COUNT=5 \
    PYTHONUNBUFFERED=1

VOLUME ["/app/vpngate_data"]

# 网页管理端口；各出口代理端口为 7928 起递增（由 EXIT_COUNT 决定数量）。
EXPOSE 8787 7928-7937

ENTRYPOINT ["python3", "vpngate_manager.py"]
