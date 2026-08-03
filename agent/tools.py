import asyncio
import contextvars
import json
import math
import os

import httpx
from datetime import datetime
from typing import Any

JAVA_BACKEND_URL = os.getenv("JAVA_BACKEND_URL", "http://localhost:8080")
ADMIN_JWT_TOKEN = os.getenv("ADMIN_JWT_TOKEN", "")

# 当前请求的用户 JWT（由 run_agent 在进入 Agent 前按请求注入，任务级隔离）
_current_user_token: contextvars.ContextVar[str] = contextvars.ContextVar("current_user_token", default="")


def set_user_token(token: str) -> None:
    _current_user_token.set(token)


def get_current_time(location: str = "中国") -> dict[str, Any]:
    """获取指定地点的当前日期和时间"""
    now = datetime.now()
    return {
        "location": location,
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": "Asia/Shanghai",
    }


def _get_headers() -> dict:
    headers = {}
    if ADMIN_JWT_TOKEN:
        headers["token"] = ADMIN_JWT_TOKEN
    return headers


def _get_user_headers() -> dict:
    """用户工具调用 Java 时携带用户 JWT，保证 /user/business/ai/** 能通过用户拦截器鉴权"""
    headers = {"Content-Type": "application/json"}
    token = _current_user_token.get()
    if token:
        headers["authentication"] = token
    return headers


async def analyze_product_sales(product_id: int, days: int = 30) -> dict[str, Any]:
    """
    分析指定商品的销售趋势
    调用 Java 后端 API: GET /admin/business/ai/product-sales?productId={id}&days={days}
    返回: 历史销量、日均销量、当前库存、预计耗尽天数
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/admin/business/ai/product-sales",
                params={"productId": product_id, "days": days},
                headers=_get_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"调用后端API失败: {str(e)}"}
        except Exception as e:
            return {"error": f"分析商品销售失败: {str(e)}"}


async def predict_stock_shortage(days_ahead: int = 7) -> list[dict[str, Any]]:
    """
    预测未来指定天数内可能缺货的商品列表
    调用 Java 后端 API: GET /admin/business/ai/stock-prediction?days={days}
    返回: [{productId, productName, currentStock, dailySales, estimatedDaysLeft}, ...]
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/admin/business/ai/stock-prediction",
                params={"days": days_ahead},
                headers=_get_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return [{"error": f"调用后端API失败: {str(e)}"}]
        except Exception as e:
            return [{"error": f"预测缺货商品失败: {str(e)}"}]


async def generate_sales_report(start_date: str, end_date: str) -> dict[str, Any]:
    """
    生成销售趋势分析报告
    调用 Java 后端 API: GET /admin/business/ai/sales-report?start={start}&end={end}
    返回: 总销售额、销量Top商品、趋势变化等
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/admin/business/ai/sales-report",
                params={"start": start_date, "end": end_date},
                headers=_get_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"调用后端API失败: {str(e)}"}
        except Exception as e:
            return {"error": f"生成销售报告失败: {str(e)}"}


async def get_inventory_overview() -> dict[str, Any]:
    """
    获取库存概览
    调用 Java 后端 API: GET /admin/business/ai/inventory-overview
    返回: 库存总量、零库存商品数、低库存商品数、各分类库存分布
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/admin/business/ai/inventory-overview",
                headers=_get_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"调用后端API失败: {str(e)}"}
        except Exception as e:
            return {"error": f"获取库存概览失败: {str(e)}"}


async def create_purchase_order(
    items: list[dict[str, Any]],
    notes: str = ""
) -> dict[str, Any]:
    """
    创建采购单（调用 Java 后端 API）
    参数 items: [{"productId": int, "productName": str, "quantity": int, "unitPrice": number}, ...]
    返回: {id, orderNumber, status, totalAmount, createTime, items, ...}
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            payload = {
                "items": [
                    {
                        "productId": item.get("productId", 0),
                        "productName": item.get("productName", ""),
                        "quantity": item.get("quantity", 0),
                        "unitPrice": item.get("unitPrice", 0),
                    }
                    for item in items
                ],
                "notes": notes,
            }
            response = await client.post(
                f"{JAVA_BACKEND_URL}/admin/purchase-order",
                json=payload,
                headers=_get_headers()
            )
            response.raise_for_status()
            result = response.json()
            if result.get("code") == 1:
                data = result["data"]
                return {
                    "orderId": data.get("id"),
                    "orderNumber": data.get("orderNumber"),
                    "createTime": data.get("createTime", ""),
                    "status": data.get("status", "PENDING"),
                    "items": data.get("items", []),
                    "totalAmount": data.get("totalAmount", 0),
                    "notes": data.get("notes", ""),
                }
            return {"error": result.get("msg", "创建采购单失败")}
        except httpx.HTTPError as e:
            return {"error": f"调用后端API失败: {str(e)}"}
        except Exception as e:
            return {"error": f"创建采购单失败: {str(e)}"}


async def list_purchase_orders(status: str = "") -> list[dict[str, Any]]:
    """
    查询采购单列表（调用 Java 后端 API）
    status 可选值: PENDING/待审核, APPROVED/已通过, RECEIVED/已收货, CANCELLED/已取消
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            params: dict[str, Any] = {"page": 1, "pageSize": 100}
            if status:
                params["status"] = status
            response = await client.get(
                f"{JAVA_BACKEND_URL}/admin/purchase-order/page",
                params=params,
                headers=_get_headers()
            )
            response.raise_for_status()
            result = response.json()
            if result.get("code") == 1:
                records = result.get("data", {}).get("records", [])
                return [
                    {
                        "orderId": o.get("id"),
                        "orderNumber": o.get("orderNumber"),
                        "createTime": o.get("createTime", ""),
                        "status": o.get("status", "PENDING"),
                        "totalAmount": o.get("totalAmount", 0),
                        "notes": o.get("notes", ""),
                    }
                    for o in records
                ]
            return [{"error": result.get("msg", "查询采购单失败")}]
        except httpx.HTTPError as e:
            return [{"error": f"调用后端API失败: {str(e)}"}]
        except Exception as e:
            return [{"error": f"查询采购单失败: {str(e)}"}]


async def generate_replenishment_plan(
    days_ahead: int = 30,
    min_stock_days: int = 7,
    safety_stock_days: int = 3,
    default_lead_time_days: int = 7,
) -> dict[str, Any]:
    """
    智能生成补货计划（核心逻辑，无需供应商数据）
    - 预测未来 days_ahead 天内的缺货风险
    - 对每个风险商品分析销售趋势
    - 计算建议采购量：日均销量 × (提前期 + 安全天数 + 最低库存天数) - 当前库存
    - 返回扁平的商品采购清单
    """
    try:
        shortages = await predict_stock_shortage(days_ahead)
        if isinstance(shortages, list) and len(shortages) > 0 and "error" in shortages[0]:
            return {"error": shortages[0]["error"]}
        if not shortages:
            return {
                "分析时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "补货周期(天)": days_ahead,
                "需补货商品数": 0,
                "商品清单": [],
                "总计建议采购金额": 0,
            }

        async def enrich_product(item: dict) -> dict | None:
            pid = item.get("productId")
            if not pid:
                return None

            daily_sales = item.get("dailySales", 0) or 0
            current_stock = item.get("currentStock", 0) or 0

            try:
                sales_data = await analyze_product_sales(pid, max(30, days_ahead))
                if isinstance(sales_data, dict) and "error" not in sales_data:
                    daily_sales = sales_data.get("dailySales", daily_sales) or daily_sales
                    current_stock = sales_data.get("currentStock", current_stock) or current_stock
            except Exception:
                pass

            lead_time = default_lead_time_days
            target_coverage_days = lead_time + safety_stock_days + min_stock_days
            target_stock = daily_sales * target_coverage_days
            suggested_qty = max(0, math.ceil(target_stock - current_stock))

            return {
                "productId": pid,
                "productName": item.get("productName", ""),
                "currentStock": current_stock,
                "dailySales": daily_sales,
                "estimatedDaysLeft": item.get("estimatedDaysLeft", 0),
                "suggestedOrderQty": suggested_qty,
                "targetStock": int(target_stock),
                "leadTimeDays": lead_time,
                "计算依据": f"日均销售{daily_sales:.1f}件 × ({lead_time}提前期 + {safety_stock_days}安全 + {min_stock_days}缓冲) - 现有{current_stock}件 = 建议采购{suggested_qty}件",
            }

        tasks = [enrich_product(item) for item in shortages if isinstance(item, dict) and "error" not in item]
        results = await asyncio.gather(*tasks)
        results = [r for r in results if r is not None]

        return {
            "分析时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "补货周期(天)": days_ahead,
            "最低库存天数": min_stock_days,
            "安全库存天数": safety_stock_days,
            "默认提前期(天)": default_lead_time_days,
            "需补货商品数": len(results),
            "商品清单": results,
            "总计建议采购金额": "见每个商品的单价，确认下单时填入实际价格",
        }
    except Exception as e:
        return {"error": f"生成补货计划失败: {str(e)}"}


# ─── 用户智能客服工具 ─────────────────────────────────────


async def search_products(
    keyword: str = "",
    category_id: int = 0,
    page: int = 1,
    page_size: int = 10
) -> dict[str, Any]:
    """
    搜索推荐商品
    调用 Java 后端 API: GET /user/business/ai/product/search
    返回: {records: [{productId, productName, price, image, sales, ...}], total, page, pageSize}
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            params: dict[str, Any] = {"page": page, "pageSize": page_size}
            if keyword:
                params["keyword"] = keyword
            if category_id > 0:
                params["categoryId"] = category_id
            response = await client.get(
                f"{JAVA_BACKEND_URL}/user/business/ai/product/search",
                params=params,
                headers=_get_user_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"搜索商品失败: {str(e)}", "records": [], "total": 0}
        except Exception as e:
            return {"error": f"搜索商品异常: {str(e)}", "records": [], "total": 0}


async def get_order_info(order_id: str) -> dict[str, Any]:
    """
    查询订单详情
    调用 Java 后端 API: GET /user/business/ai/order/detail/{orderId}
    返回: {orderId, status, amount, address, items, createTime, ...}
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/user/business/ai/order/detail/{order_id}",
                headers=_get_user_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"查询订单失败: {str(e)}"}
        except Exception as e:
            return {"error": f"查询订单异常: {str(e)}"}


async def get_order_history(page: int = 1, page_size: int = 10) -> dict[str, Any]:
    """
    查看历史订单列表
    调用 Java 后端 API: GET /user/business/ai/order/list?page={page}&pageSize={pageSize}
    返回: {records: [{orderId, status, totalAmount, createTime, ...}], total, page, pageSize}
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/user/business/ai/order/list",
                params={"page": page, "pageSize": page_size},
                headers=_get_user_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"查询订单列表失败: {str(e)}", "records": [], "total": 0}
        except Exception as e:
            return {"error": f"查询订单列表异常: {str(e)}", "records": [], "total": 0}


async def update_order_address(
    order_id: str,
    new_address: str,
    contact_name: str = "",
    contact_phone: str = ""
) -> dict[str, Any]:
    """
    修改订单收货地址
    调用 Java 后端 API: PUT /user/business/ai/order/address
    参数: {orderId, newAddress, contactName, contactPhone}
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            payload = {
                "orderId": order_id,
                "newAddress": new_address,
                "contactName": contact_name,
                "contactPhone": contact_phone,
            }
            response = await client.put(
                f"{JAVA_BACKEND_URL}/user/business/ai/order/address",
                json=payload,
                headers=_get_user_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"修改地址失败: {str(e)}"}
        except Exception as e:
            return {"error": f"修改地址异常: {str(e)}"}


async def get_user_default_address(user_id: str = "") -> dict[str, Any]:
    """
    获取用户的默认收货地址
    调用 Java 后端 API: GET /user/business/ai/address/default
    返回: {consignee, phone, fullAddress, label}
    注意：Java 端从用户 JWT 获取 userId，无需（也不应）传 userId
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                f"{JAVA_BACKEND_URL}/user/business/ai/address/default",
                headers=_get_user_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"获取默认地址失败: {str(e)}"}
        except Exception as e:
            return {"error": f"获取默认地址异常: {str(e)}"}


async def create_user_order(
    items: list[dict[str, Any]],
    address_detail: str,
    consignee: str,
    phone: str,
    remark: str = "",
    user_id: str = ""
) -> dict[str, Any]:
    """
    为用户创建订单
    调用 Java 后端 API: POST /user/business/ai/order/create
    参数 items: [{"productId": int, "name": str, "quantity": int}, ...]
    返回: {orderId, orderNumber, amount, createTime}
    注意：Java 端从用户 JWT 获取 userId，忽略请求体中的 userId
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            payload = {
                "items": items,
                "addressDetail": address_detail,
                "consignee": consignee,
                "phone": phone,
                "remark": remark,
                "userId": user_id,
            }
            response = await client.post(
                f"{JAVA_BACKEND_URL}/user/business/ai/order/create",
                json=payload,
                headers=_get_user_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"创建订单失败: {str(e)}"}
        except Exception as e:
            return {"error": f"创建订单异常: {str(e)}"}


async def apply_refund(
    order_id: str,
    reason: str,
    refund_amount: float = 0
) -> dict[str, Any]:
    """
    申请退款
    调用 Java 后端 API: PUT /user/business/ai/order/refund
    参数: {orderId, reason, refundAmount}
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            payload = {
                "orderId": order_id,
                "reason": reason,
                "refundAmount": refund_amount,
            }
            response = await client.put(
                f"{JAVA_BACKEND_URL}/user/business/ai/order/refund",
                json=payload,
                headers=_get_user_headers()
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            return {"error": f"申请退款失败: {str(e)}"}
        except Exception as e:
            return {"error": f"申请退款异常: {str(e)}"}


# ─── 工具列表定义 ────────────────────────────────────────

_ADMIN_ONLY = ["analyze_product_sales", "predict_stock_shortage",
               "generate_sales_report", "get_inventory_overview",
               "create_purchase_order", "list_purchase_orders",
               "generate_replenishment_plan"]

_USER_ONLY = ["search_products", "get_order_info", "get_order_history",
              "update_order_address", "apply_refund", "create_user_order",
              "get_user_default_address"]

_COMMON = ["get_current_time"]

_ALL_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取指定地点的当前日期和时间",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "地点名称，如'北京'、'东京'",
                    }
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_product_sales",
            "description": "分析指定商品的销售趋势，返回历史销量、日均销量、当前库存、预计耗尽天数",
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "商品ID",
                    },
                    "days": {
                        "type": "integer",
                        "description": "统计天数，默认30天",
                        "default": 30,
                    }
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "predict_stock_shortage",
            "description": "预测未来指定天数内可能缺货的商品列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "预测未来天数，默认7天",
                        "default": 7,
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_sales_report",
            "description": "生成指定日期范围的销售趋势分析报告",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "开始日期，格式YYYY-MM-DD",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "结束日期，格式YYYY-MM-DD",
                    }
                },
                "required": ["start_date", "end_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inventory_overview",
            "description": "获取库存概览，包括库存总量、零库存商品数、低库存商品数、各分类库存分布",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_purchase_order",
            "description": "创建采购单（本地存储）。items格式: [{\"productId\": 商品ID, \"productName\": \"商品名\", \"quantity\": 数量, \"unitPrice\": 单价}]",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "采购商品列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "productId": {"type": "integer", "description": "商品ID"},
                                "productName": {"type": "string", "description": "商品名称"},
                                "quantity": {"type": "integer", "description": "采购数量"},
                                "unitPrice": {"type": "number", "description": "单价"},
                            },
                            "required": ["productId", "quantity"],
                        },
                    },
                    "notes": {
                        "type": "string",
                        "description": "备注说明",
                        "default": "",
                    },
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_purchase_orders",
            "description": "查询采购单列表（本地存储）。status可选值: PENDING/待审核, APPROVED/已通过, RECEIVED/已收货, CANCELLED/已取消",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "采购单状态筛选，留空查全部",
                        "default": "",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_replenishment_plan",
            "description": "智能生成补货计划：预测缺货风险→分析销售趋势→计算建议采购量。返回扁平的商品采购清单",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "预测未来天数，默认30天",
                        "default": 30,
                    },
                    "min_stock_days": {
                        "type": "integer",
                        "description": "期望维持的最低库存天数，默认7天",
                        "default": 7,
                    },
                    "safety_stock_days": {
                        "type": "integer",
                        "description": "安全库存天数，默认3天",
                        "default": 3,
                    },
                    "default_lead_time_days": {
                        "type": "integer",
                        "description": "采购提前期天数，默认7天",
                        "default": 7,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "搜索推荐商品，支持按关键词和分类查找",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，如'手机'、'牛奶'",
                        "default": "",
                    },
                    "category_id": {
                        "type": "integer",
                        "description": "分类ID，按分类筛选",
                        "default": 0,
                    },
                    "page": {
                        "type": "integer",
                        "description": "页码，从1开始",
                        "default": 1,
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "每页条数",
                        "default": 10,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_info",
            "description": "查询订单详情，需要提供订单ID",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单ID",
                    }
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_history",
            "description": "查看历史订单列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "page": {
                        "type": "integer",
                        "description": "页码",
                        "default": 1,
                    },
                    "page_size": {
                        "type": "integer",
                        "description": "每页条数",
                        "default": 10,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_order_address",
            "description": "修改订单的收货地址，需要订单ID和新地址",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单ID",
                    },
                    "new_address": {
                        "type": "string",
                        "description": "新收货地址",
                    },
                    "contact_name": {
                        "type": "string",
                        "description": "联系人姓名",
                        "default": "",
                    },
                    "contact_phone": {
                        "type": "string",
                        "description": "联系电话",
                        "default": "",
                    },
                },
                "required": ["order_id", "new_address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_refund",
            "description": "申请退款，需要订单ID和退款原因",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "订单ID",
                    },
                    "reason": {
                        "type": "string",
                        "description": "退款原因",
                    },
                    "refund_amount": {
                        "type": "number",
                        "description": "退款金额，0表示全额退款",
                        "default": 0,
                    },
                },
                "required": ["order_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_user_order",
            "description": "为用户创建订单，生成购物订单并返回订单信息。下单成功后请告知用户订单金额和订单号，并询问是否需要去支付",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "商品列表，每项包含productId、name、quantity",
                        "items": {
                            "type": "object",
                            "properties": {
                                "productId": {"type": "integer", "description": "商品ID"},
                                "name": {"type": "string", "description": "商品名称"},
                                "quantity": {"type": "integer", "description": "购买数量"},
                            },
                            "required": ["productId", "name", "quantity"],
                        },
                    },
                    "address_detail": {
                        "type": "string",
                        "description": "收货地址",
                    },
                    "consignee": {
                        "type": "string",
                        "description": "收货人姓名",
                    },
                    "phone": {
                        "type": "string",
                        "description": "联系电话",
                    },
                    "remark": {
                        "type": "string",
                        "description": "订单备注",
                        "default": "",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "用户ID",
                    },
                },
                "required": ["items", "address_detail", "consignee", "phone", "user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_default_address",
            "description": "获取用户的默认收货地址（包含联系人、电话、详细地址），下单前调用此工具自动获取地址信息，无需用户手动输入",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "用户ID",
                    },
                },
                "required": ["user_id"],
            },
        },
    },
]

_ALL_TOOL_MAP = {
    "get_current_time": get_current_time,
    "analyze_product_sales": analyze_product_sales,
    "predict_stock_shortage": predict_stock_shortage,
    "generate_sales_report": generate_sales_report,
    "get_inventory_overview": get_inventory_overview,
    "create_purchase_order": create_purchase_order,
    "list_purchase_orders": list_purchase_orders,
    "generate_replenishment_plan": generate_replenishment_plan,
    "search_products": search_products,
    "get_order_info": get_order_info,
    "get_order_history": get_order_history,
    "update_order_address": update_order_address,
    "apply_refund": apply_refund,
    "create_user_order": create_user_order,
    "get_user_default_address": get_user_default_address,
}

ADMIN_TOOLS = [d for d in _ALL_TOOL_DEFS if d["function"]["name"] in (_COMMON + _ADMIN_ONLY)]
USER_TOOLS = [d for d in _ALL_TOOL_DEFS if d["function"]["name"] in (_COMMON + _USER_ONLY)]

ADMIN_TOOL_MAP = {k: v for k, v in _ALL_TOOL_MAP.items() if k in (_COMMON + _ADMIN_ONLY)}
USER_TOOL_MAP = {k: v for k, v in _ALL_TOOL_MAP.items() if k in (_COMMON + _USER_ONLY)}
