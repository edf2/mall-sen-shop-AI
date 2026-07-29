import json
import asyncio
import logging
import re as regex
from typing import AsyncGenerator, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, MessagesState, StateGraph

from agent.config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, MODEL_NAME, REDIS_URL, REDIS_TTL
from agent.redis_memory import RedisChatMemory
from agent.tools import ADMIN_TOOLS, ADMIN_TOOL_MAP, USER_TOOLS, USER_TOOL_MAP

logger = logging.getLogger(__name__)

memory = RedisChatMemory(REDIS_URL, ttl=REDIS_TTL)

llm = ChatOpenAI(
    model=MODEL_NAME,
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL,
    temperature=0,
)

# ─── 商家 AI ───────────────────────────────────────────

ADMIN_SYSTEM_PROMPT = """你是一个商家智能助手，可以分析销售数据、预测库存缺货、生成补货计划并管理采购单。
你可以使用以下工具：
- analyze_product_sales: 分析指定商品的销售趋势
- predict_stock_shortage: 预测未来可能缺货的商品列表
- generate_sales_report: 生成指定日期范围的销售趋势分析报告
- get_inventory_overview: 获取库存概览
- get_current_time: 获取当前时间
- generate_replenishment_plan: 【核心】智能生成补货计划——预测缺货、分析销售趋势、计算建议采购量
- create_purchase_order: 创建采购单（本地存储）
- list_purchase_orders: 查询采购单列表

推荐工作流程：
1. 商家询问备货建议 → 调用 generate_replenishment_plan 生成补货清单
2. 展示清单给商家（含商品名、当前库存、日均销量、建议采购量、计算依据）
3. 商家确认后 → 调用 create_purchase_order 创建采购单（从清单中选商品填入数量和单价）
4. 商家想查看进度 → 调用 list_purchase_orders 查询已创建的采购单

对于补货计划，展示时要清晰列出每件商品的建议采购量和计算依据。
请使用清晰、专业的中文回答。先调用工具获取数据再进行分析。"""

admin_llm_with_tools = llm.bind_tools(ADMIN_TOOLS)


def admin_call_model(state: MessagesState) -> dict:
    messages = [SystemMessage(content=ADMIN_SYSTEM_PROMPT), *state["messages"]]
    response = admin_llm_with_tools.invoke(messages)
    return {"messages": [response]}


def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1]
    return "tools" if isinstance(last, AIMessage) and last.tool_calls else END


async def admin_execute_tools(state: MessagesState) -> dict:
    last: AIMessage = state["messages"][-1]
    tool_messages = []
    for tc in last.tool_calls:
        fn = ADMIN_TOOL_MAP.get(tc["name"])
        if fn:
            try:
                result = await fn(**tc.get("args", {})) if asyncio.iscoroutinefunction(fn) else fn(**tc.get("args", {}))
            except Exception as e:
                result = {"error": f"工具执行失败: {str(e)}"}
            tool_messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tc["id"]))
        else:
            tool_messages.append(ToolMessage(content=f"未知工具: {tc['name']}", tool_call_id=tc["id"]))
    return {"messages": tool_messages}


admin_workflow = StateGraph(MessagesState)
admin_workflow.add_node("agent", admin_call_model)
admin_workflow.add_node("tools", admin_execute_tools)
admin_workflow.set_entry_point("agent")
admin_workflow.add_conditional_edges("agent", should_continue)
admin_workflow.add_edge("tools", "agent")
admin_app = admin_workflow.compile()


# ─── 用户 AI ───────────────────────────────────────────

USER_SYSTEM_PROMPT = """你是一个微信商城的智能客服助手，帮助用户查找商品、管理订单、处理退款、修改收货地址和代为下单。

你可以使用以下工具：
- search_products: 搜索推荐商品，支持按关键词和分类查找
- get_order_info: 查询订单详情
- get_order_history: 查看历史订单列表
- update_order_address: 修改订单的收货地址（需要订单ID和新地址）
- apply_refund: 申请退款（需要订单ID和退款原因）
- get_user_default_address: 获取用户的默认收货地址（自动获取联系人、电话、详细地址，无需用户手动输入）
- create_user_order: 【核心】为用户创建订单（需要商品列表、收货地址、联系人、电话和用户ID）
- get_current_time: 获取当前时间

下单流程（重要）：
1. 用户表达下单意向后，先通过 search_products 搜索商品确认用户想要的商品
2. 确认商品信息（名称、价格、数量）
3. 调用 get_user_default_address 自动获取用户的默认收货地址（无需问用户地址信息）
4. 调用 create_user_order 创建订单（自动将获取的地址信息传入）
5. 如果没有默认地址，再询问用户手动提供收货地址、联系人和电话
6. 下单成功后，清晰告知用户订单金额和订单号，并询问是否要去支付
7. 提醒用户订单需在15分钟内完成支付，超时订单将自动取消

请根据用户的提问分析用户意图，选择合适的工具：
- 用户想买东西、找商品 → 调用 search_products（帮用户推荐合适的商品）
- 用户要下单 → 按照上述下单流程逐步操作（先调search_products，再调get_user_default_address，最后调create_user_order）
- 用户想查某个订单 → 调用 get_order_info
- 用户想看所有订单 → 调用 get_order_history
- 用户想改地址 → 调用 update_order_address（先获取订单信息确认）
- 用户想退款 → 调用 apply_refund（先获取订单信息确认）

如果用户意图不明确，先友好地询问用户想做什么。
如果用户要求的操作缺少必要信息（如订单ID），先问清楚再执行。
回答时请使用友好、亲切的中文，像真实客服一样沟通。"""

user_llm_with_tools = llm.bind_tools(USER_TOOLS)


def user_call_model(state: MessagesState) -> dict:
    messages = [SystemMessage(content=USER_SYSTEM_PROMPT), *state["messages"]]
    response = user_llm_with_tools.invoke(messages)
    return {"messages": [response]}


async def user_execute_tools(state: MessagesState) -> dict:
    last: AIMessage = state["messages"][-1]
    tool_messages = []
    for tc in last.tool_calls:
        fn = USER_TOOL_MAP.get(tc["name"])
        if fn:
            try:
                result = await fn(**tc.get("args", {})) if asyncio.iscoroutinefunction(fn) else fn(**tc.get("args", {}))
            except Exception as e:
                result = {"error": f"工具执行失败: {str(e)}"}
            tool_messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tc["id"]))
        else:
            tool_messages.append(ToolMessage(content=f"未知工具: {tc['name']}", tool_call_id=tc["id"]))
    return {"messages": tool_messages}


user_workflow = StateGraph(MessagesState)
user_workflow.add_node("agent", user_call_model)
user_workflow.add_node("tools", user_execute_tools)
user_workflow.set_entry_point("agent")
user_workflow.add_conditional_edges("agent", should_continue)
user_workflow.add_edge("tools", "agent")
user_app = user_workflow.compile()


# ─── 路由 ──────────────────────────────────────────────

def _get_app(role: str):
    return admin_app if role == "admin" else user_app


async def run_agent(user_message: str, role: str = "user", user_id: str = "", session_id: str = "") -> str:
    app = _get_app(role)

    history = await memory.get_messages(session_id)
    msgs = []
    if user_id:
        msgs.append(SystemMessage(content=f"当前用户ID: {user_id}（你在调用 get_user_default_address 和 create_user_order 时，请使用此 user_id 参数）"))
    msgs.append(HumanMessage(content=user_message))
    inputs = {"messages": history + msgs}
    result = await app.ainvoke(inputs)

    await memory.save_messages(session_id, result["messages"])
    await memory.register_session(session_id, role)
    for msg in reversed(result["messages"]):
        if isinstance(msg, AIMessage) and msg.content:
            reply = msg.content

            # 扫描消息历史，检测是否有 create_user_order 成功调用 → 注入 __ORDER_DATA__
            for i, m in enumerate(result["messages"]):
                if isinstance(m, AIMessage) and m.tool_calls:
                    for tc in m.tool_calls:
                        if tc.get("name") == "create_user_order":
                            target_id = tc["id"]
                            for j in range(i + 1, len(result["messages"])):
                                tm = result["messages"][j]
                                if isinstance(tm, ToolMessage) and tm.tool_call_id == target_id:
                                    try:
                                        data = json.loads(tm.content)
                                        if isinstance(data, dict) and data.get("code") == 1 and data.get("data"):
                                            order = data["data"]
                                            marker = "__ORDER_DATA__:" + json.dumps(order, ensure_ascii=False)
                                            reply += "\n\n" + marker
                                    except Exception:
                                        pass
                                    break
                            break
            return reply
    return "抱歉，我没有生成有效的回复。"


async def run_agent_stream(user_message: str, role: str = "user", session_id: str = "") -> AsyncGenerator[str, None]:
    app = _get_app(role)

    history = await memory.get_messages(session_id)
    inputs = {"messages": history + [HumanMessage(content=user_message)]}

    collected = []
    saved = False

    try:
        async for event in app.astream_events(inputs, version="v1"):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    collected.append(content)
                    yield content
    finally:
        if not saved and session_id and collected:
            full_msgs = history + [
                HumanMessage(content=user_message),
                AIMessage(content="".join(collected)),
            ]
            try:
                await memory.save_messages(session_id, full_msgs)
                await memory.register_session(session_id, role)
                saved = True
            except Exception as e:
                logger.error(f"保存记忆失败: {e}")
