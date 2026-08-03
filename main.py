import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

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
# AGENT_API_KEY：调用 /agent/** 与 /api/** 必须携带请求头 x-agent-key 且与此一致。
# 安全背景：该服务同时承载「商家采购单增删改」与「所有用户会话/对话历史」，
# 若对外暴露且无鉴权，任何人可越权读写他人对话或篡改采购数据。
# Java 端 AgentClientConfig 会统一注入该请求头（sky.agent.api-key）。
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "change-me")

# 明确受保护的前缀（其余为 public：健康检查、静态调试页、Swagger）
_PROTECTED_PREFIXES = ("/agent/", "/api/")


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.url.path.startswith(_PROTECTED_PREFIXES):
        if not secrets.compare_digest(request.headers.get("x-agent-key", ""), AGENT_API_KEY):
            logger.warning("Agent 服务鉴权失败: 401 %s (source=%s)", request.url.path, request.client.host if request.client else "?")
            return JSONResponse(status_code=401, content={"code": 0, "msg": "非法请求：缺少或错误的 x-agent-key"})
    return await call_next(request)


# ─── 采购订单代理（转发到 Java 后端）────────────────────
JAVA_BACKEND_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080")
ADMIN_JWT_TOKEN = os.getenv("ADMIN_JWT_TOKEN", "")


def _get_java_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if ADMIN_JWT_TOKEN:
        headers["token"] = ADMIN_JWT_TOKEN
    return headers


@app.get("/api/purchase-orders")
async def list_purchase_orders(status: Optional[str] = Query(None)):
    try:
        params: dict = {"page": 1, "pageSize": 100}
        if status:
            params["status"] = status
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/admin/purchase-order/page",
                params=params, headers=_get_java_headers()
            )
            response.raise_for_status()
            result = response.json()
            if result.get("code") == 1:
                records = result.get("data", {}).get("records", [])
                # 转换为前端兼容格式
                orders = [
                    {
                        "orderId": o.get("id"),
                        "orderNumber": o.get("orderNumber"),
                        "createTime": o.get("createTime", ""),
                        "status": o.get("status", "PENDING"),
                        "totalAmount": o.get("totalAmount", 0),
                        "notes": o.get("notes", ""),
                        "items": [],
                    }
                    for o in records
                ]
                return {"code": 1, "data": orders, "total": len(orders)}
            return {"code": 0, "data": [], "total": 0, "msg": result.get("msg", "")}
    except Exception as e:
        logger.error(f"查询采购单失败: {e}")
        return {"code": 0, "data": [], "total": 0, "msg": str(e)}


@app.get("/api/purchase-orders/{order_id}")
async def get_purchase_order(order_id: int):
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/admin/purchase-order/{order_id}",
                headers=_get_java_headers()
            )
            response.raise_for_status()
            result = response.json()
            if result.get("code") == 1:
                data = result["data"]
                order = {
                    "orderId": data.get("id"),
                    "orderNumber": data.get("orderNumber"),
                    "createTime": data.get("createTime", ""),
                    "status": data.get("status", "PENDING"),
                    "items": [
                        {
                            "productId": i.get("productId"),
                            "productName": i.get("productName", ""),
                            "quantity": i.get("quantity", 0),
                            "unitPrice": i.get("unitPrice", 0),
                            "subtotal": i.get("subtotal", 0),
                        }
                        for i in (data.get("items") or [])
                    ],
                    "totalAmount": data.get("totalAmount", 0),
                    "notes": data.get("notes", ""),
                }
                return {"code": 1, "data": order}
            raise HTTPException(status_code=404, detail=result.get("msg", "采购单不存在"))
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="采购单不存在")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


class POItem(BaseModel):
    productId: int
    productName: str = ""
    quantity: int
    unitPrice: float = 0


class CreatePORequest(BaseModel):
    items: list[POItem]
    notes: str = ""


class UpdatePOStatusRequest(BaseModel):
    status: str


@app.post("/api/purchase-orders")
async def create_purchase_order(req: CreatePORequest):
    try:
        payload = {
            "items": [
                {
                    "productId": item.productId,
                    "productName": item.productName,
                    "quantity": item.quantity,
                    "unitPrice": item.unitPrice,
                }
                for item in req.items
            ],
            "notes": req.notes,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{JAVA_BACKEND_URL}/admin/purchase-order",
                json=payload, headers=_get_java_headers()
            )
            response.raise_for_status()
            result = response.json()
            if result.get("code") == 1:
                data = result["data"]
                order = {
                    "orderId": data.get("id"),
                    "orderNumber": data.get("orderNumber"),
                    "createTime": data.get("createTime", ""),
                    "status": data.get("status", "PENDING"),
                    "items": [
                        {
                            "productId": i.get("productId"),
                            "productName": i.get("productName", ""),
                            "quantity": i.get("quantity", 0),
                            "unitPrice": i.get("unitPrice", 0),
                            "subtotal": i.get("subtotal", 0),
                        }
                        for i in (data.get("items") or [])
                    ],
                    "totalAmount": data.get("totalAmount", 0),
                    "notes": data.get("notes", ""),
                }
                return {"code": 1, "data": order}
            raise HTTPException(status_code=500, detail=result.get("msg", "创建失败"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建采购单失败: {str(e)}")


@app.put("/api/purchase-orders/{order_id}/status")
async def update_purchase_order_status(order_id: int, req: UpdatePOStatusRequest):
    valid_statuses = ["PENDING", "APPROVED", "RECEIVED", "CANCELLED"]
    if req.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"无效状态，可选: {', '.join(valid_statuses)}")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(
                f"{JAVA_BACKEND_URL}/admin/purchase-order/{order_id}/status",
                json={"status": req.status}, headers=_get_java_headers()
            )
            response.raise_for_status()
            result = response.json()
            if result.get("code") == 1:
                return {"code": 1, "msg": "状态更新成功"}
            raise HTTPException(status_code=500, detail=result.get("msg", "更新失败"))
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="采购单不存在")
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@app.delete("/api/purchase-orders/{order_id}")
async def delete_purchase_order(order_id: int):
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.delete(
                f"{JAVA_BACKEND_URL}/admin/purchase-order/{order_id}",
                headers=_get_java_headers()
            )
            response.raise_for_status()
            result = response.json()
            if result.get("code") == 1:
                return {"code": 1, "msg": "删除成功"}
            raise HTTPException(status_code=500, detail=result.get("msg", "删除失败"))
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail="采购单不存在")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


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


@app.get("/admin", include_in_schema=False)
async def admin_page():
    with open("static/admin.html", encoding="utf-8") as f:
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
    reply = await run_agent(request.message, request.role, user_id=request.user_id or "", session_id=request.session_id, token=request.token)
    return ChatResponse(reply=reply, session_id=request.session_id)


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
    # 仅监听本机回环地址，进一步收紧网络暴露面（配合 /agent、/api 的 x-agent-key 鉴权）
    uvicorn.run("main:app", host="127.0.0.1", port=8100, reload=False)
