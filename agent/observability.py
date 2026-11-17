"""
AI 可观测性接入（Arize Phoenix，本地开源，零密钥、零外网依赖）。

设计要点（面试可讲）：
1. 接入方式：Phoenix 基于 OpenTelemetry，LangChain/LangGraph 通过官方
   OpenInference 插桩器接入 —— 一次 instrument() 全局生效，自动捕获
   LLM 调用（输入/输出/token 消耗/耗时）、LangGraph 图节点流转、工具执行链，
   不需要逐个挂 callback。
2. 数据完全落本地：终端 `phoenix serve` 起看板（默认 http://localhost:6006），
   不依赖任何账号、密钥和境外网络。相比此前的 Langfuse Cloud 方案，
   彻底消除了「密钥 401 / 区域 host 不匹配 / 网络不通」三类故障面。
3. 三层 fail-safe（沿用 Langfuse 时期的哲学：可观测性是旁路，任何一层故障
   都只丢追踪、不丢业务，与 AGENT_API_KEY 的 fail-fast 刻意相反）：
   - 第 1 层：未安装依赖包 → 警告并禁用；
   - 第 2 层：初始化/插桩异常 → 警告并禁用；
   - 第 3 层：本地 phoenix 服务未启动 → OTel 后台批处理导出失败只丢追踪，
     业务请求零感知。

环境变量（.env，全部可选）：
    PHOENIX_ENDPOINT=http://localhost:6006/v1/traces   # 改这个可接远端 collector
    PHOENIX_PROJECT_NAME=mall-sen-shop-AI
"""
import logging
import os

logger = logging.getLogger(__name__)

_ENDPOINT = os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006/v1/traces")
_PROJECT = os.getenv("PHOENIX_PROJECT_NAME", "mall-sen-shop-AI")

# 第 1 层 fail-safe：没装包 → 自动禁用（项目照常运行，只是没追踪）
_ENABLED = False

try:
    from phoenix.otel import register
    from openinference.instrumentation.langchain import LangChainInstrumentor
except ImportError:
    logger.warning(
        "未安装 arize-phoenix / openinference-instrumentation-langchain，本次运行不追踪"
        "（安装：uv pip install arize-phoenix openinference-instrumentation-langchain）"
    )
else:
    try:
        # 第 2 层 fail-safe：初始化失败 → 禁用，不崩
        _tracer_provider = register(project_name=_PROJECT, endpoint=_ENDPOINT)
        LangChainInstrumentor().instrument(tracer_provider=_tracer_provider)
        _ENABLED = True
        logger.info("Phoenix 可观测性已启用（endpoint=%s, project=%s）", _ENDPOINT, _PROJECT)
    except Exception as e:  # noqa: BLE001 —— 观测故障绝不能拖死主流程
        logger.warning("Phoenix 初始化失败，本次运行不追踪: %s", e)


def make_config(session_id: str = "", user_id: str = "", role: str = ""):
    """
    为一次 Agent 运行构造 LangChain run config。

    - 未启用时返回 None，调用方行为与接入前完全一致；
    - 启用时返回仅含 metadata 的 config —— 插桩是全局的，会话/用户归属
      靠 OpenInference 语义约定属性：session.id / user.id（Phoenix 据此
      聚合多轮会话时间线），agent.role 对应原方案的 trace_name。
    """
    if not _ENABLED:
        return None
    meta = {}
    if session_id:
        meta["session.id"] = session_id
    if user_id:
        meta["user.id"] = user_id
    if role:
        meta["agent.role"] = role
    return {"metadata": meta} if meta else None