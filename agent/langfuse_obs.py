"""
Langfuse 可观测性接入（fail-safe：未配置密钥时自动禁用，绝不影响业务）。

设计要点（面试可讲）：
1. 接入方式：langfuse 官方的 LangChain 集成入口 CallbackHandler，挂在
   app.ainvoke / app.astream_events 的 config["callbacks"] 上——自动捕获：
   LLM 调用（输入/输出/token 消耗/耗时）、LangGraph 图节点流转、工具执行链。
   不需要在 18 个工具里手写任何打点代码。
2. 每次请求创建一个新 handler 实例：一个实例对应一条 trace（一次用户请求的
   完整调用链），复用旧实例会把多轮请求混进同一条 trace。
3. 三层 fail-safe（与 config.py 的 fail-fast 哲学相反，故意的）：
   AGENT_API_KEY 是安全必需项，缺了必须拒绝启动；而可观测性是旁路，
   任何一层出问题都只丢追踪、不丢业务——观测挂了不能拖死主流程。

环境变量（.env，全部可选）：
    LANGFUSE_PUBLIC_KEY=pk-lf-xxxx      # Langfuse Cloud 项目设置里的 API Keys
    LANGFUSE_SECRET_KEY=sk-lf-xxxx
    LANGFUSE_HOST=https://cloud.langfuse.com   # 自托管时改成 http://localhost:3000
"""
import logging
import os

logger = logging.getLogger(__name__)

# 第 1 层 fail-safe：没配置密钥 → 自动禁用（项目照常运行，只是没追踪）
_ENABLED = bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))

if _ENABLED:
    try:
        # 第 2 层 fail-safe：设置了密钥但没装 langfuse 包 → 警告并禁用，不崩
        from langfuse.langchain import CallbackHandler as _LFHandler
        logger.info("Langfuse 可观测性已启用（host=%s）", os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"))
    except ImportError:
        logger.warning("已设置 LANGFUSE 密钥但未安装 langfuse（python -m pip install langfuse），本次运行不追踪")
        _ENABLED = False


def make_handler(session_id: str = "", user_id: str = "", role: str = ""):
    """
    为一次 Agent 运行创建追踪 handler；未启用/创建失败时返回 None，
    调用方拿到 None 就不挂 callback，行为与接入前完全一致。

    【版本坑（面试可讲）：langfuse v3 → v5 两次 API 变更】
    - v3：trace_name / session_id / user_id / tags 作为 handler 构造参数传入；
    - v5（当前 5.2）：构造函数只吃 public_key 和 trace_context，trace 元数据改从
      LangChain run 的 metadata 读，约定键 langfuse_trace_name / langfuse_session_id /
      langfuse_user_id（tags 仍走 config["tags"]）。
    所以 v5 的正确姿势是：handler 无参构造 + LangChain config 里带 metadata。

    返回 (handler, metadata) 二元组：handler=None 表示未启用；metadata 是要挂到
    LangChain config["metadata"] 上的字典（v3 时为空 dict，元数据已在 handler 里）。
    """
    if not _ENABLED:
        return None, {}
    try:
        # 第 3 层 fail-safe：单个 handler 创建失败 → 只丢这一次的追踪
        try:
            # langfuse v5：无参构造（认证走环境变量），元数据由调用方挂 config
            _LFHandler()
            metadata = {}
            if session_id:
                metadata["langfuse_session_id"] = session_id
            if user_id:
                metadata["langfuse_user_id"] = user_id
            if role:
                metadata["langfuse_trace_name"] = f"agent-{role}"
            return _LFHandler(), metadata
        except TypeError:
            # langfuse v3：老签名，元数据进构造参数
            return _LFHandler(
                trace_name=f"agent-{role or 'user'}",
                session_id=session_id or None,
                user_id=user_id or None,
                tags=["mall-sen-shop-AI", role or "user"],
            ), {}
    except Exception as e:
        logger.warning("创建 Langfuse handler 失败，本次运行不追踪: %s", e)
        return None, {}
