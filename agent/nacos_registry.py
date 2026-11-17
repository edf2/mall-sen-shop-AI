"""
Nacos 服务注册模块
将 Python AI 服务注册到 Nacos，使 Gateway 能够发现并路由到该服务。
"""
import logging
import os
import threading
import time

import nacos
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Nacos 配置
NACOS_SERVER = os.getenv("NACOS_ADDR", "127.0.0.1:8848")
SERVICE_NAME = "mall-sen-ai"
SERVICE_IP = os.getenv("SERVICE_IP", "127.0.0.1")
SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8100"))
WEIGHT = 1.0
HEALTHY = True
EPHEMERAL = True
CLUSTER_NAME = "DEFAULT"


def register_to_nacos():
    """注册服务到 Nacos"""
    try:
        client = nacos.NacosClient(NACOS_SERVER, namespace="")
        client.add_naming_instance(
            service_name=SERVICE_NAME,
            ip=SERVICE_IP,
            port=SERVICE_PORT,
            weight=WEIGHT,
            healthy=HEALTHY,
            ephemeral=EPHEMERAL,
            cluster_name=CLUSTER_NAME,
            metadata={
                "service-type": "ai-agent",
                "version": "1.0.0",
            },
        )
        logger.info(f"AI 服务已注册到 Nacos: {SERVICE_NAME} -> {SERVICE_IP}:{SERVICE_PORT}")

        # 心跳线程
        def heartbeat():
            while True:
                try:
                    client.heartbeat(nacos_instance_id=None)
                except Exception as e:
                    logger.warning(f"Nacos 心跳失败: {e}")
                time.sleep(5)

        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        logger.info("Nacos 心跳线程已启动")

    except Exception as e:
        logger.error(f"Nacos 注册失败: {e}")
        logger.warning("AI 服务将以独立模式运行（不注册到 Nacos）")


def deregister_from_nacos():
    """从 Nacos 注销服务"""
    try:
        client = nacos.NacosClient(NACOS_SERVER, namespace="")
        client.remove_naming_instance(
            service_name=SERVICE_NAME,
            ip=SERVICE_IP,
            port=SERVICE_PORT,
            ephemeral=EPHEMERAL,
        )
        logger.info(f"AI 服务已从 Nacos 注销: {SERVICE_NAME}")
    except Exception as e:
        logger.warning(f"Nacos 注销失败: {e}")
