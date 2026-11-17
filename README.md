# MALL 森百货 · AI 智能体服务（mall-sen-shop-AI）

> Mall 森百货电商（Java 后端 [Mall-Sen-shop](https://github.com/edf2/Mall-Sen-shop)）的 AI 智能体服务层：
> **商家补货分析助手 + 用户智能客服** 双 Agent，LangGraph 工具调用循环驱动，工具全部对接 Java 后端真实 API。
>
> Python (FastAPI + LangGraph + LangChain) · Redis 会话记忆 · SSE 流式输出 · Langfuse 可观测性

## 架构总览

```
微信小程序 / Vue3 管理端
        │  (SSE 流式 / JSON)
        ▼
Java 后端 (Spring Boot 3, :8080)  ──x-agent-key──▶  本服务 (FastAPI, :8100)
        ▲                                              │
        │  HTTP 调用（带鉴权头）                        ▼
   91 个业务接口 ◀────────────────────  LangGraph 双工作流
                                                   │
                                    ┌───────────────┴───────────────┐
                                    ▼                               ▼
                            商家 Agent（admin）                用户 Agent（user）
                            销售分析/补货/采购单               查商品/查订单/改地址/下单
                                    │                               │
                                    └───────────┬───────────────────┘
                                                ▼
                                     15 个 Function Calling 工具
                                     （全部调 Java 真实接口，非 mock）
                                                ▼
                                     Redis 会话记忆（TTL）
```

**核心机制（Agent ≠ 一问一答的聊天 API）：**
LLM 节点推理决策 → 决定调用哪个工具 → 路由到工具节点执行 → 结果回填消息列表 → 再喂回 LLM → 循环直到 LLM 不再发起 `tool_calls`（ReAct 模式）。`agent/agent.py` 的 `_build_workflow()` 用同一工厂函数构建商家/用户两条 StateGraph，复用工具执行器。

## 双 Agent 与工具清单（15 个，全部真实接口）

**商家智能助手（admin）——预测缺货、生成补货计划、管理采购单：**

| 工具 | 作用 |
|---|---|
| `analyze_product_sales` | 分析指定商品销售趋势（历史销量/日均/预计耗尽天数） |
| `predict_stock_shortage` | 预测未来 N 天可能缺货的商品列表 |
| `generate_replenishment_plan` | **核心**：智能生成补货计划（预测+趋势+建议采购量+计算依据） |
| `create_purchase_order` / `list_purchase_orders` | 创建/查询采购单 |
| `generate_sales_report` / `get_inventory_overview` | 销售报告 / 库存概览 |

**用户智能客服（user）——像真客服一样完成全流程：**

| 工具 | 作用 |
|---|---|
| `search_products` | 按关键词/分类搜索商品（支持商品卡片推荐） |
| `create_user_order` | **核心**：代用户下单（自动取默认地址，含下单全流程） |
| `get_order_info` / `get_order_history` | 查订单详情 / 历史订单 |
| `update_order_address` | 修改收货地址 |
| `apply_refund` | 申请退款 |
| `get_user_default_address` | 自动获取默认地址（免用户手动输入） |

## 关键设计决策（面试/协作可讲）

1. **鉴权：x-agent-key 共享密钥替代 JWT**。
   AI 初版用静态管理员 JWT 调 Java 接口，8 天 TTL 过期后**整个商家 AI 静默失效**且无刷新机制（排查"AI 突然全部工具报 401"时定位到）。改为无过期时间的共享密钥：Java 端 `JwtTokenAdminInterceptor` 对 `/admin/business/ai/**` 放行并校验 `x-agent-key`。本服务对等防护：`/agent/**` 入口同样要求该密钥（`secrets.compare_digest` 防时序攻击）。
2. **任务级 token 隔离**：用户工具以 `contextvars.ContextVar` 注入当前请求的用户 JWT（而非全局变量），并发会话互不串号；async 上下文安全。
3. **三层 fail-safe 的可观测性**（`agent/langfuse_obs.py`）：未配密钥→自动禁用；配了没装包→警告降级；单 handler 异常→只丢本次追踪。**可观测性是旁路，任何一层故障都不能影响业务**——与 `AGENT_API_KEY` 的 fail-fast（安全必需项，缺了拒绝启动）刻意相反。
4. **会话记忆**：`RedisChatMemory` 按会话存全量消息（含工具调用历史），TTL 过期；ZSet 索引支持会话列表/回放。多轮上下文里 Agent 能"记得"之前查过什么。
5. **结构化事件提取**：从对话流里提取订单数据（`__ORDER_DATA__`）与商品卡片（`[PRODUCTS:ID]` 标记），前端据此渲染订单确认页/商品卡片——LLM 自然语言输出之外的第二数据通道。

## 快速开始

```bash
# 1. 环境：Python ≥3.10（项目用 uv 管理依赖，pip 亦可）
#    依赖见 pyproject.toml：fastapi / langgraph / langchain-openai / redis / httpx / uvicorn

# 2. 配置
cp .env.example .env
# 必填：
#   DASHSCOPE_API_KEY  —— 阿里云百炼 API Key（模型 qwen 系列）
#   AGENT_API_KEY      —— 与 Java 后端 application.yml 的 agent.service.api-key 一致（32 位强随机串）
# 可选（观测）：
#   LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST —— 配了即启用追踪，不配自动禁用

# 3. 前置服务
#    Java 后端 :8080（Mall-Sen-shop） + Redis :6379

# 4. 启动
python main.py          # 监听 127.0.0.1:8100（仅回环地址，配合密钥鉴权收紧暴露面）

# 5. 验证
#    打开 http://127.0.0.1:8100/ 调试聊天页（会自动带 x-agent-key）
#    商家模式问："帮我看看哪些商品快缺货了" → 触发 预测缺货→补货计划 工具链
#    用户模式问："有没有可乐" → search_products + 商品卡片
```

## 项目结构

```
mall-sen-shop-AI/
├── main.py                  # FastAPI 入口：SSE 流式 /agent/chat/stream、鉴权中间件、Nacos 注册
├── agent/
│   ├── agent.py             # LangGraph 双工作流构建 + 工具执行器 + 结构化数据提取
│   ├── tools.py             # 15 个 Function Calling 工具（httpx 调 Java API，双鉴权头）
│   ├── redis_memory.py      # RedisChatMemory：会话消息持久化 + ZSet 会话索引
│   ├── langfuse_obs.py      # Langfuse 追踪接入（v5 API，三层 fail-safe，含版本兼容层）
│   ├── config.py            # 环境变量加载（安全项 fail-fast）
│   └── nacos_registry.py    # 服务注册（可选，失败不影响启动）
├── static/chat.html         # 本机调试聊天页（自动带 x-agent-key）
├── pyproject.toml / uv.lock
└── .env.example
```

## API 摘要

| 端点 | 说明 |
|---|---|
| `POST /agent/chat` | 同步对话（JSON 进 JSON 出，含订单/商品结构化数据） |
| `POST /agent/chat/stream` | **SSE 流式**对话（token 级流式 + `__ORDER_DATA__`/`__PRODUCT_DATA__` 事件） |
| `GET /agent/sessions` | 按 role 列出会话（ZSet 索引） |
| `GET /agent/sessions/{id}/messages` | 回放某会话全量消息 |
| `GET /health` | 健康检查 |

所有 `/agent/**` 需请求头 `x-agent-key`。

## 已知限制与后续方向

- 计划中：RAG 商品知识库（chunking + 向量检索）、LLM 调用重试与本地模型降级、评测集回归测试；
- 商家补货预测依赖 Java 端的销量统计算法，Agent 层做编排与解释，不做数值计算；
- 会话记忆为全量保存，超长对话的 token 成本控制（滑动窗口/摘要压缩）待优化。

> AI 辅助开发、人工架构与验收：本项目为个人学习/求职作品，代码经 AI 辅助生成，**架构设计、关键决策（鉴权方案、降级策略、记忆设计）与踩坑修复均由本人主导并逐行验证**——包括 JWT 静默失效排障、Langfuse v3→v5 API 迁移、Windows 压测端口耗尽排障等。


