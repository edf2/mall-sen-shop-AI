import json
import logging
import time
from typing import List, Optional

from langchain_core.messages import BaseMessage, message_to_dict, messages_from_dict
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisChatMemory:
    def __init__(self, redis_url: str, ttl: int = 86400):
        self.redis_url = redis_url
        self.ttl = ttl
        self._client: Optional[aioredis.Redis] = None

    async def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(self.redis_url, decode_responses=True)
        return self._client

    async def get_messages(self, session_id: str) -> List[BaseMessage]:
        if not session_id:
            return []
        try:
            client = await self._get_client()
            key = f"session:{session_id}:messages"
            data = await client.get(key)
            if data is None:
                return []
            raw = json.loads(data)
            return messages_from_dict(raw)
        except Exception as e:
            logger.warning(f"Redis get_messages 失败 (session={session_id}): {e}")
            return []

    async def save_messages(self, session_id: str, messages: List[BaseMessage]):
        if not session_id:
            return
        try:
            client = await self._get_client()
            key = f"session:{session_id}:messages"
            raw = [message_to_dict(m) for m in messages]
            await client.setex(key, self.ttl, json.dumps(raw, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"Redis save_messages 失败 (session={session_id}): {e}")

    async def register_session(self, session_id: str, role: str):
        if not session_id or not role:
            return
        try:
            client = await self._get_client()
            key = f"sessions:{role}"
            now = time.time()
            await client.zadd(key, {session_id: now})
            await client.expire(key, self.ttl)
        except Exception as e:
            logger.warning(f"Redis register_session 失败: {e}")

    async def list_sessions(self, role: str, limit: int = 50, offset: int = 0) -> list[dict]:
        if not role:
            return []
        try:
            client = await self._get_client()
            key = f"sessions:{role}"
            raw = await client.zrevrange(key, offset, offset + limit - 1, withscores=True)
            result = []
            for sid, timestamp in raw:
                if isinstance(sid, bytes):
                    sid = sid.decode()
                msg_key = f"session:{sid}:messages"
                msg_data = await client.get(msg_key)
                message_count = 0
                preview = ""
                if msg_data:
                    try:
                        msgs = json.loads(msg_data)
                        message_count = len(msgs)
                        for m in msgs:
                            if m.get("type") == "human":
                                preview = m.get("data", {}).get("content", "")[:60]
                                break
                    except Exception:
                        pass
                result.append({
                    "session_id": sid,
                    "created_at": int(timestamp),
                    "message_count": message_count,
                    "preview": preview,
                })
            return result
        except Exception as e:
            logger.warning(f"Redis list_sessions 失败: {e}")
            return []

    async def get_session_messages(self, session_id: str) -> list[dict]:
        if not session_id:
            return []
        try:
            client = await self._get_client()
            key = f"session:{session_id}:messages"
            data = await client.get(key)
            if data is None:
                return []
            return json.loads(data)
        except Exception as e:
            logger.warning(f"Redis get_session_messages 失败: {e}")
            return []

    async def clear(self, session_id: str):
        if not session_id:
            return
        try:
            client = await self._get_client()
            await client.delete(f"session:{session_id}:messages")
        except Exception as e:
            logger.warning(f"Redis clear 失败 (session={session_id}): {e}")
