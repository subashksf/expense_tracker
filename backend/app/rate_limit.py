import math
import re
import time
from dataclasses import dataclass

from fastapi import Request
from redis import Redis

from .config import Settings

TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local now_ms = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refill_per_sec = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local ttl_seconds = tonumber(ARGV[5])

local data = redis.call("HMGET", key, "tokens", "ts")
local tokens = tonumber(data[1])
local ts = tonumber(data[2])

if tokens == nil then
  tokens = capacity
end
if ts == nil then
  ts = now_ms
end

local elapsed_sec = 0
if now_ms > ts then
  elapsed_sec = (now_ms - ts) / 1000.0
end

tokens = math.min(capacity, tokens + (elapsed_sec * refill_per_sec))
local allowed = 0
local retry_after_ms = 0

if tokens >= requested then
  tokens = tokens - requested
  allowed = 1
else
  local missing = requested - tokens
  if refill_per_sec > 0 then
    retry_after_ms = math.ceil((missing / refill_per_sec) * 1000.0)
  else
    retry_after_ms = 60000
  end
end

redis.call("HMSET", key, "tokens", tokens, "ts", now_ms)
redis.call("EXPIRE", key, ttl_seconds)

return {allowed, tokens, retry_after_ms}
"""


@dataclass
class RateLimitPolicy:
    name: str
    capacity: int
    refill_per_sec: float
    requested_tokens: int = 1

    @property
    def ttl_seconds(self) -> int:
        if self.refill_per_sec <= 0:
            return 300
        drain_seconds = self.capacity / self.refill_per_sec
        return int(max(60, math.ceil(drain_seconds * 2)))


@dataclass
class RateLimitDecision:
    allowed: bool
    remaining_tokens: float
    retry_after_ms: int
    policy: RateLimitPolicy
    error: str | None = None


def _to_int(value, fallback: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return fallback


def _to_float(value, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return fallback


class RedisTokenBucketLimiter:
    def __init__(self, redis_url: str, key_prefix: str = "rl") -> None:
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self._client: Redis | None = None

    @property
    def client(self) -> Redis:
        if self._client is None:
            self._client = Redis.from_url(self.redis_url)
        return self._client

    def consume(self, policy: RateLimitPolicy, identity: str) -> RateLimitDecision:
        key = f"{self.key_prefix}:{policy.name}:{identity}"
        now_ms = int(time.time() * 1000)
        try:
            raw = self.client.eval(
                TOKEN_BUCKET_LUA,
                1,
                key,
                now_ms,
                policy.capacity,
                policy.refill_per_sec,
                policy.requested_tokens,
                policy.ttl_seconds,
            )
            allowed = _to_int(raw[0], 0) == 1 if isinstance(raw, list) else True
            remaining = _to_float(raw[1], 0.0) if isinstance(raw, list) else 0.0
            retry_after_ms = _to_int(raw[2], 0) if isinstance(raw, list) else 0
            return RateLimitDecision(
                allowed=allowed,
                remaining_tokens=max(0.0, remaining),
                retry_after_ms=max(0, retry_after_ms),
                policy=policy,
            )
        except Exception as exc:  # noqa: BLE001
            return RateLimitDecision(
                allowed=True,
                remaining_tokens=float(policy.capacity),
                retry_after_ms=0,
                policy=policy,
                error=str(exc),
            )


def _policy_from_per_minute(name: str, per_minute: int) -> RateLimitPolicy:
    safe = max(1, int(per_minute))
    refill_per_sec = safe / 60.0
    return RateLimitPolicy(name=name, capacity=safe, refill_per_sec=refill_per_sec)


def pick_rate_limit_policy(method: str, path: str, settings: Settings) -> RateLimitPolicy:
    normalized_method = method.upper()
    strict_routes = {
        ("POST", f"{settings.api_prefix}/imports"),
        ("POST", f"{settings.api_prefix}/transactions/recategorize"),
        ("POST", f"{settings.api_prefix}/duplicate-reviews/bulk-resolve"),
    }
    if (normalized_method, path) in strict_routes:
        return _policy_from_per_minute("strict", settings.rate_limit_strict_per_minute)
    if normalized_method in {"GET", "HEAD"}:
        return _policy_from_per_minute("read", settings.rate_limit_read_per_minute)
    return _policy_from_per_minute("write", settings.rate_limit_write_per_minute)


def _normalize_key_part(raw: str, max_len: int = 128) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9:._-]+", "_", raw.strip())
    return (cleaned[:max_len] or "unknown").lower()


def resolve_rate_limit_identity(request: Request) -> str:
    user_id = request.headers.get("x-user-id", "").strip()
    if user_id:
        return f"user:{_normalize_key_part(user_id)}"

    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return f"ip:{_normalize_key_part(first)}"

    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return f"ip:{_normalize_key_part(real_ip)}"

    host = request.client.host if request.client else "unknown"
    return f"ip:{_normalize_key_part(host)}"

