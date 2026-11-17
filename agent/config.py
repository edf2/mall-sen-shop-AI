import os

from dotenv import load_dotenv

load_dotenv(override=True)


def _require(name: str) -> str:
    """读取必填环境变量，缺失或仍是占位符时直接抛错，避免用弱默认值静默放行。"""
    value = os.getenv(name)
    if not value or value in ("change-me", "REPLACE_ME", "PENDING"):
        raise RuntimeError(
            f"缺少必填环境变量 {name}：请在 .env 中配置强随机密钥后重启服务，"
            f"禁止使用 change-me / REPLACE_ME / PENDING 等占位值。"
        )
    return value


DASHSCOPE_API_KEY = _require("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

MODEL_NAME = os.getenv("MODEL_NAME", "qwen3.8-flash")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
REDIS_TTL = int(os.getenv("REDIS_TTL", "86400"))

# 智能体服务对外 /agent/** 的共享密钥，与 Java 后端 agent.service.api-key 保持一致。
# 缺失或为占位值直接抛错（fail-fast），绝不回落为可破的默认值。
AGENT_API_KEY = _require("AGENT_API_KEY")
