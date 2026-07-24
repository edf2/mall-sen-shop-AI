import json
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import StreamingResponse

from agent.schemas import ChatRequest, ChatResponse
from agent.agent import run_agent, run_agent_stream

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Sky Agent Service 启动中...")
    yield
    logger.info("Sky Agent Service 关闭中...")


app = FastAPI(title="Sky Agent Service", version="1.0.0", lifespan=lifespan,
              docs_url=None, redoc_url="/redoc")


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
    from fastapi.responses import HTMLResponse
    with open("static/chat.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/agent/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    logger.info(f"收到请求: session={request.session_id}, role={request.role}, message={request.message}")
    reply = await run_agent(request.message, request.role)
    return ChatResponse(reply=reply, session_id=request.session_id)


@app.post("/agent/chat/stream")
async def chat_stream(request: ChatRequest):
    logger.info(f"收到流式请求: session={request.session_id}, role={request.role}, message={request.message}")

    async def generate():
        try:
            async for chunk in run_agent_stream(request.message, request.role):
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


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8100, reload=False)
