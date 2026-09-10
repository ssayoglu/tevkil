import time
import json
from typing import List, Tuple, Optional, Dict, Any
import redis.asyncio as aioredis
from bot.config import settings

_redis_client: Optional[aioredis.Redis] = None


def get_redis_client() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


class _RedisProxy:
    def __getattr__(self, name):
        return getattr(get_redis_client(), name)


redis_client = _RedisProxy()


class RedisQueueService:
    @staticmethod
    async def add_applicant(
        listing_id: int,
        user_id: int,
        user_data: Dict[str, Any],
        custom_score_ms: Optional[float] = None
    ) -> Tuple[bool, int, float]:
        """
        Kullanıcıyı milisaniye (ve varsa handikap) skoruyla Sorted Set'e ekler.
        Dönüş: (is_new: bool, rank: int, applied_score_ms: float)
        """
        now_ms = custom_score_ms if custom_score_ms is not None else (time.time() * 1000.0)
        key = f"listing:{listing_id}:applicants"
        info_key = f"user_info:{user_id}"

        # Kullanıcı detaylarını sakla
        await redis_client.set(info_key, json.dumps(user_data), ex=86400 * 7)

        # ZADD ile ekle (NX=True: Sadece daha önce eklenmemişse ekle)
        added = await redis_client.zadd(key, {str(user_id): now_ms}, nx=True)
        
        # Kullanıcının sırasını bul (0-indexed)
        rank = await redis_client.zrank(key, str(user_id))
        rank_1_based = (rank + 1) if rank is not None else -1

        # Eğer zaten varsa ilk eklenme zamanını al
        if not added:
            score = await redis_client.zscore(key, str(user_id))
            return False, rank_1_based, float(score or now_ms)

        return True, rank_1_based, now_ms

    @staticmethod
    async def get_applicant_rank(listing_id: int, user_id: int) -> Optional[int]:
        key = f"listing:{listing_id}:applicants"
        rank = await redis_client.zrank(key, str(user_id))
        return (rank + 1) if rank is not None else None

    @staticmethod
    async def get_all_applicants(listing_id: int) -> List[Dict[str, Any]]:
        """
        Tüm başvuranları milisaniye sırasına göre kullanıcı ve rank puanı bilgileriyle döndürür.
        """
        key = f"listing:{listing_id}:applicants"
        items = await redis_client.zrange(key, 0, -1, withscores=True)
        
        results = []
        for index, (uid_str, score) in enumerate(items, start=1):
            user_id = int(uid_str)
            info_key = f"user_info:{user_id}"
            user_info_raw = await redis_client.get(info_key)
            user_info = json.loads(user_info_raw) if user_info_raw else {}
            
            results.append({
                "rank": index,
                "user_id": user_id,
                "score_ms": float(score),
                "full_name": user_info.get("full_name", f"Kullanıcı {user_id}"),
                "username": user_info.get("username"),
                "rank_score": user_info.get("rank_score", 100),
                "penalty_points": user_info.get("penalty_points", 0),
                "handicap_level": user_info.get("handicap_level", 0),
                "is_baro_verified": user_info.get("is_baro_verified", False),
            })
        return results

    @staticmethod
    async def get_first_applicant(listing_id: int) -> Optional[Tuple[int, float]]:
        key = f"listing:{listing_id}:applicants"
        items = await redis_client.zrange(key, 0, 0, withscores=True)
        if items:
            uid, score = items[0]
            return int(uid), float(score)
        return None

    @staticmethod
    async def get_next_available_applicant(listing_id: int, current_rank: int) -> Optional[Tuple[int, float, int]]:
        """
        current_rank (1-based) sonrasındaki sıradaki adayı getirir.
        Örneğin current_rank=1 ise index 1'deki adayı (2. sıra) getirir.
        Dönüş: (user_id, score_ms, new_rank)
        """
        key = f"listing:{listing_id}:applicants"
        # 1-based current_rank için index = current_rank (yani 1. adayın sonrası index 1)
        items = await redis_client.zrange(key, current_rank, current_rank, withscores=True)
        if items:
            uid, score = items[0]
            return int(uid), float(score), current_rank + 1
        return None

    @staticmethod
    async def set_active_bridge(user_id: int, session_data: Dict[str, Any]):
        """
        Kullanıcının şu anda aktif bir köprü oturumunda olduğunu kaydeder.
        """
        key = f"active_bridge:{user_id}"
        await redis_client.set(key, json.dumps(session_data), ex=86400)

    @staticmethod
    async def get_active_bridge(user_id: int) -> Optional[Dict[str, Any]]:
        key = f"active_bridge:{user_id}"
        data = await redis_client.get(key)
        return json.loads(data) if data else None

    @staticmethod
    async def remove_active_bridge(user_id: int):
        key = f"active_bridge:{user_id}"
        await redis_client.delete(key)

    @staticmethod
    async def flush_all_active_bridges():
        """Tüm aktif köprü oturumu redis anahtarlarını temizler."""
        try:
            keys = await redis_client.keys("active_bridge:*")
            if keys:
                await redis_client.delete(*keys)
        except Exception:
            pass

    @staticmethod
    async def acquire_update_lock(listing_id: int, timeout_sec: float = 1.0) -> bool:
        """
        Telegram rate limit koruması için grup mesaj güncelleme kilidi.
        """
        lock_key = f"lock:update_msg:{listing_id}"
        res = await redis_client.set(lock_key, "1", nx=True, px=int(timeout_sec * 1000))
        return bool(res)

    @staticmethod
    async def push_pending_message(user_id: int, message_payload: Dict[str, Any]):
        """
        Kullanıcı botu henüz başlatmamışsa mesajı Redis kuyruğunda bekletir.
        """
        key = f"pending_msgs:{user_id}"
        await redis_client.rpush(key, json.dumps(message_payload))
        await redis_client.expire(key, 86400)

    @staticmethod
    async def pop_all_pending_messages(user_id: int) -> List[Dict[str, Any]]:
        """
        Kullanıcının bekleyen tüm mesajlarını çeker ve kuyruktan temizler.
        """
        key = f"pending_msgs:{user_id}"
        items = await redis_client.lrange(key, 0, -1)
        if items:
            await redis_client.delete(key)
            return [json.loads(x) for x in items]
        return []

    @staticmethod
    async def set_admin_listing_message_id(listing_id: int, message_id: int):
        """
        Admin grubundaki ana ilan mesajının ID'sini saklar (Thread/Reply gruplama için).
        """
        key = f"admin_msg:listing:{listing_id}"
        await redis_client.set(key, str(message_id), ex=86400 * 30)

    @staticmethod
    async def get_admin_listing_message_id(listing_id: int) -> Optional[int]:
        """
        Admin grubundaki ana ilan mesajının ID'sini döner.
        """
        key = f"admin_msg:listing:{listing_id}"
        val = await redis_client.get(key)
        return int(val) if val else None

    @staticmethod
    async def add_known_group(group_id: int):
        """
        Grubu bilinen gruplar setine ekler.
        """
        await redis_client.sadd("known_groups", str(group_id))

    @staticmethod
    async def get_known_groups() -> List[int]:
        """
        Kayıtlı bilinen grup ID'lerini döner.
        """
        try:
            members = await redis_client.smembers("known_groups")
            res = []
            for m in members:
                try:
                    res.append(int(m))
                except ValueError:
                    pass
            return res
        except Exception:
            return []
