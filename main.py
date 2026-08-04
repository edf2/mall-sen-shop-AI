import json
import logging
import os
import secrets
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from agent.schemas import ChatRequest, ChatResponse
from agent.agent import run_agent, run_agent_stream, memory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Sky Agent Service 启动中...")
    yield
    logger.info("Sky Agent Service 关闭中...")


app = FastAPI(title="Sky Agent Service", version="1.0.0", lifespan=lifespan,
              docs_url=None, redoc_url="/redoc")

# ─── 内部鉴权 ─────────────────────────────────────────
# AGENT_API_KEY：调用 /agent/** 必须携带请求头 x-agent-key 且与此一致。
# 安全背景：该服务承载「所有用户会话/对话历史」与对 Java 后端的 AI 数据调用，
# 若对外暴露且无鉴权，任何人可越权读写他人对话。
# Java 端 AgentClientConfig 会统一注入该请求头（sky.agent.api-key）。
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "change-me")

# 明确受保护的前缀（其余为 public：健康检查、Swagger、聊天页）
_PROTECTED_PREFIXES = ("/agent/",)


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.url.path.startswith(_PROTECTED_PREFIXES):
        if not secrets.compare_digest(request.headers.get("x-agent-key", ""), AGENT_API_KEY):
            logger.warning("Agent 服务鉴权失败: 401 %s (source=%s)", request.url.path, request.client.host if request.client else "?")
            return JSONResponse(status_code=401, content={"code": 0, "msg": "非法请求：缺少或错误的 x-agent-key"})
    return await call_next(request)


# 说明：采购订单的增删改查已移除。采购单管理是 Java 后端（/admin/purchase-order/**）
# 与商家后台（project-sky-admin-vue-ts）的 BFF 职责，不属 Agent 服务；此前在此暴露的
# /api/purchase-orders 全量 CRUD 代理 + admin.html 调试页已删除，避免职责重叠与静态
# ADMIN_JWT_TOKEN 过期（8 天 TTL）后整个商家 AI 静默失效。Agent 工具调用 Java 后端时
# 使用不设过期时间的共享密钥 x-agent-key（见 agent/tools.py），无需刷新。

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        swagger_js_url="https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.17.14/swagger-ui-bundle.min.js",
        swagger_css_url="https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.17.14/swagger-ui.min.css",
    )


@app.get("/", include_in_schema=False)
async def chat_page():
    with open("static/chat.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _validate_message(message: str) -> None:
    """校验对话消息：非空 + 长度限制"""
    if not message or not message.strip():
        raise HTTPException(status_code=400, detail="message 不能为空")
    if len(message) > 2000:
        raise HTTPException(status_code=400, detail="message 过长，最多2000字符")


@app.post("/agent/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    logger.info(f"收到请求: session={request.session_id}, role={request.role}, message={request.message}, user_id={request.user_id}")
    _validate_message(request.message)
    reply, order_data = await run_agent(request.message, request.role, user_id=request.user_id or "", session_id=request.session_id, token=request.token)
    return ChatResponse(reply=reply, session_id=request.session_id, order_data=order_data)


@app.post("/agent/chat/stream")
async def chat_stream(request: ChatRequest):
    logger.info(f"收到流式请求: session={request.session_id}, role={request.role}, message={request.message}")
    _validate_message(request.message)

    async def generate():
        try:
            async for chunk in run_agent_stream(request.message, request.role, session_id=request.session_id, token=request.token):
                data = json.dumps({"token": chunk, "session_id": request.session_id}, ensure_ascii=False)
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error(f"流式输出异常: {e}")
            error_data = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/agent/sessions")
async def list_sessions(role: str = "user", limit: int = 50, offset: int = 0):
    sessions = await memory.list_sessions(role, limit, offset)
    return {"code": 1, "data": sessions}


@app.get("/agent/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    messages = await memory.get_session_messages(session_id)
    return {"code": 1, "data": messages}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    # 仅监听本机回环地址，进一步收紧网络暴露面（配合 /agent 的 x-agent-key 鉴权）
    uvicorn.run("main:app", host="127.0.0.1", port=8100, reload=False)
