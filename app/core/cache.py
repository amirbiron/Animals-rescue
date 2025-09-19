"""
Redis Cache and Rate Limiting System
מערכת מטמון ובקרת קצב עם Redis

This module provides Redis-based caching, rate limiting, and session management
for the Animal Rescue Bot system. Includes sophisticated rate limiting algorithms,
distributed locking, and high-performance caching utilities.
"""

import asyncio
import hashlib
import json
import pickle
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Union, Callable
from typing import Tuple
from functools import wraps

import redis.asyncio as redis
import redis as redis_sync
from redis.exceptions import (
    BusyLoadingError,
    ConnectionError as RedisConnectionError,
    TimeoutError as RedisTimeoutError,
)
import structlog
from redis.retry import Retry
from redis.backoff import ExponentialBackoff

from app.core.config import settings
from app.core.exceptions import RateLimitError

# =============================================================================
# Logger Setup
# =============================================================================

logger = structlog.get_logger(__name__)

# =============================================================================
# Redis Client Configuration
# =============================================================================

class RedisConfig:
    """Redis connection configuration and client management."""
    
    def __init__(self):
        self.host = settings.REDIS_HOST
        self.port = settings.REDIS_PORT
        self.db = settings.REDIS_DB
        self.password = settings.REDIS_PASSWORD
        self.max_connections = settings.REDIS_MAX_CONNECTIONS
        
        # Connection pool configuration
        self.connection_kwargs = {
            "host": self.host,
            "port": self.port,
            "db": self.db,
            "password": self.password,
            "decode_responses": True,
            "socket_timeout": 5,
            "socket_connect_timeout": 5,
            "health_check_interval": 30,
            "max_connections": self.max_connections,
            "retry_on_error": [
                BusyLoadingError,
                RedisConnectionError,
                RedisTimeoutError,
            ],
            "retry": Retry(
                backoff=ExponentialBackoff(),
                retries=3,
            ),
        }
    
    def create_client(self, db: Optional[int] = None) -> redis.Redis:
        """Create Redis client with optimal configuration."""
        kwargs = self.connection_kwargs.copy()
        if db is not None:
            kwargs["db"] = db
        
        return redis.Redis(**kwargs)

    def create_sync_client(self, db: Optional[int] = None) -> redis_sync.Redis:
        """Create synchronous Redis client (for RQ/Scheduler)."""
        kwargs = self.connection_kwargs.copy()
        # RQ expects byte responses; avoid automatic decoding
        kwargs["decode_responses"] = False
        if db is not None:
            kwargs["db"] = db
        return redis_sync.Redis(**kwargs)


# Global Redis clients
_redis_config = RedisConfig()

# Main Redis client for caching
redis_client = _redis_config.create_client()

# Separate client for job queues (uses DB 1)
redis_queue_client = _redis_config.create_client(db=1)

# Synchronous client for RQ/Scheduler (uses DB 1)
redis_queue_sync = _redis_config.create_sync_client(db=1)

# Session storage client (uses DB 2)
redis_session_client = _redis_config.create_client(db=2)

# =============================================================================
# Custom Exceptions
# =============================================================================

class CacheError(Exception):
    """Base exception for cache operations."""
    pass


class RateLimitExceeded(RateLimitError):
    """Rate limit exceeded exception."""
    
    def __init__(self, message: str, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class LockAcquisitionError(Exception):
    """Failed to acquire distributed lock."""
    pass


# =============================================================================
# Advanced Caching System
# =============================================================================

class CacheManager:
    """
    Advanced Redis-based cache manager.
    
    Features:
    - Automatic serialization/deserialization
    - Cache warming and preloading
    - Tag-based invalidation
    - Compression for large objects
    - Cache statistics and monitoring
    - Distributed cache consistency
    """
    
    def __init__(self, client: redis.Redis = redis_client, prefix: str = "cache"):
        self.client = client
        self.prefix = prefix
        self.stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
            "errors": 0,
        }
    
    def _make_key(self, key: str, namespace: str = "") -> str:
        """Generate standardized cache key."""
        parts = [self.prefix]
        if namespace:
            parts.append(namespace)
        parts.append(key)
        return ":".join(parts)
    
    def _serialize_value(self, value: Any) -> bytes:
        """Serialize value for storage."""
        try:
            # Try JSON first for simple types
            json_str = json.dumps(value, default=str)
            return f"json:{json_str}".encode('utf-8')
        except (TypeError, ValueError):
            # Fall back to pickle for complex objects
            pickled = pickle.dumps(value)
            return b"pickle:" + pickled
    
    def _deserialize_value(self, data: bytes) -> Any:
        """Deserialize value from storage."""
        if data.startswith(b"json:"):
            json_str = data[5:].decode('utf-8')
            return json.loads(json_str)
        elif data.startswith(b"pickle:"):
            pickled_data = data[7:]
            return pickle.loads(pickled_data)
        else:
            # Legacy string format
            return data.decode('utf-8')
    
    async def get(
        self, 
        key: str, 
        namespace: str = "",
        default: Any = None
    ) -> Any:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            namespace: Optional namespace for key organization
            default: Default value if key not found
            
        Returns:
            Cached value or default
        """
        try:
            cache_key = self._make_key(key, namespace)
            data = await self.client.get(cache_key)
            
            if data is None:
                self.stats["misses"] += 1
                logger.debug("Cache miss", key=cache_key)
                return default
            
            self.stats["hits"] += 1
            logger.debug("Cache hit", key=cache_key)
            
            # Handle both binary and string data
            if isinstance(data, str):
                data = data.encode('utf-8')
            
            return self._deserialize_value(data)
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error("Cache get failed", key=key, error=str(e))
            return default
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        namespace: str = "",
        tags: Optional[List[str]] = None
    ) -> bool:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
            namespace: Optional namespace for key organization
            tags: Tags for grouped invalidation
            
        Returns:
            True if set successfully
        """
        try:
            cache_key = self._make_key(key, namespace)
            serialized_value = self._serialize_value(value)
            
            if ttl:
                result = await self.client.setex(cache_key, ttl, serialized_value)
            else:
                result = await self.client.set(cache_key, serialized_value)
            
            if result:
                self.stats["sets"] += 1
                logger.debug("Cache set", key=cache_key, ttl=ttl)
                
                # Handle tags for invalidation
                if tags:
                    await self._add_tags(cache_key, tags)
                
                return True
            
            return False
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error("Cache set failed", key=key, error=str(e))
            return False
    
    async def delete(self, key: str, namespace: str = "") -> bool:
        """Delete key from cache."""
        try:
            cache_key = self._make_key(key, namespace)
            result = await self.client.delete(cache_key)
            
            if result:
                self.stats["deletes"] += 1
                logger.debug("Cache delete", key=cache_key)
                return True
            
            return False
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error("Cache delete failed", key=key, error=str(e))
            return False
    
    async def exists(self, key: str, namespace: str = "") -> bool:
        """Check if key exists in cache."""
        try:
            cache_key = self._make_key(key, namespace)
            return bool(await self.client.exists(cache_key))
        except Exception as e:
            logger.error("Cache exists check failed", key=key, error=str(e))
            return False
    
    async def expire(self, key: str, ttl: int, namespace: str = "") -> bool:
        """Set expiration time for existing key."""
        try:
            cache_key = self._make_key(key, namespace)
            return bool(await self.client.expire(cache_key, ttl))
        except Exception as e:
            logger.error("Cache expire failed", key=key, error=str(e))
            return False
    
    async def get_many(
        self, 
        keys: List[str], 
        namespace: str = ""
    ) -> Dict[str, Any]:
        """Get multiple values from cache."""
        if not keys:
            return {}
        
        try:
            cache_keys = [self._make_key(key, namespace) for key in keys]
            values = await self.client.mget(cache_keys)
            
            result = {}
            for original_key, cache_key, value in zip(keys, cache_keys, values):
                if value is not None:
                    try:
                        if isinstance(value, str):
                            value = value.encode('utf-8')
                        result[original_key] = self._deserialize_value(value)
                        self.stats["hits"] += 1
                    except Exception as e:
                        logger.error("Deserialization failed", key=cache_key, error=str(e))
                        self.stats["errors"] += 1
                else:
                    self.stats["misses"] += 1
            
            logger.debug("Cache multi-get", requested=len(keys), found=len(result))
            return result
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error("Cache multi-get failed", keys=keys, error=str(e))
            return {}
    
    async def set_many(
        self,
        mapping: Dict[str, Any],
        ttl: Optional[int] = None,
        namespace: str = ""
    ) -> bool:
        """Set multiple key-value pairs."""
        if not mapping:
            return True
        
        try:
            # Prepare data for pipeline
            pipe = self.client.pipeline()
            
            for key, value in mapping.items():
                cache_key = self._make_key(key, namespace)
                serialized_value = self._serialize_value(value)
                
                if ttl:
                    pipe.setex(cache_key, ttl, serialized_value)
                else:
                    pipe.set(cache_key, serialized_value)
            
            results = await pipe.execute()
            
            success_count = sum(1 for result in results if result)
            self.stats["sets"] += success_count
            
            logger.debug("Cache multi-set", requested=len(mapping), successful=success_count)
            
            return success_count == len(mapping)
            
        except Exception as e:
            self.stats["errors"] += 1
            logger.error("Cache multi-set failed", error=str(e))
            return False
    
    async def _add_tags(self, cache_key: str, tags: List[str]):
        """Add cache key to tag sets for grouped invalidation."""
        try:
            pipe = self.client.pipeline()
            
            for tag in tags:
                tag_key = self._make_key(f"tag:{tag}")
                pipe.sadd(tag_key, cache_key)
                pipe.expire(tag_key, 86400)  # Tags expire after 24 hours
            
            await pipe.execute()
            
        except Exception as e:
            logger.error("Failed to add cache tags", tags=tags, error=str(e))
    
    async def invalidate_tag(self, tag: str) -> int:
        """Invalidate all cache keys with a specific tag."""
        try:
            tag_key = self._make_key(f"tag:{tag}")
            
            # Get all keys with this tag
            cache_keys = await self.client.smembers(tag_key)
            
            if not cache_keys:
                return 0
            
            # Delete all keys
            deleted_count = await self.client.delete(*cache_keys)
            
            # Remove the tag set
            await self.client.delete(tag_key)
            
            logger.info("Cache tag invalidated", tag=tag, keys_deleted=deleted_count)
            return deleted_count
            
        except Exception as e:
            logger.error("Cache tag invalidation failed", tag=tag, error=str(e))
            return 0
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            info = await self.client.info("memory")
            keyspace_info = await self.client.info("keyspace")
            
            return {
                "hits": self.stats["hits"],
                "misses": self.stats["misses"],
                "hit_rate": (
                    self.stats["hits"] / (self.stats["hits"] + self.stats["misses"]) 
                    if (self.stats["hits"] + self.stats["misses"]) > 0 else 0
                ),
                "sets": self.stats["sets"],
                "deletes": self.stats["deletes"],
                "errors": self.stats["errors"],
                "memory_used": info.get("used_memory_human", "unknown"),
                "memory_peak": info.get("used_memory_peak_human", "unknown"),
                "keyspace": keyspace_info,
            }
        except Exception as e:
            logger.error("Failed to get cache stats", error=str(e))
            return self.stats.copy()


# Global cache manager instance
cache = CacheManager()

# =============================================================================
# Advanced Rate Limiting System
# =============================================================================

class RateLimiter:
    """
    Advanced Redis-based rate limiting with multiple algorithms.
    
    Supports:
    - Token bucket algorithm
    - Fixed window counter
    - Sliding window log
    - Sliding window counter
    - Distributed rate limiting
    """
    
    def __init__(self, client: redis.Redis = redis_client):
        self.client = client
    
    async def check_token_bucket(
        self,
        key: str,
        capacity: int,
        refill_rate: int,
        tokens_requested: int = 1,
        window: int = 60
    ) -> Tuple[bool, int]:
        """
        Token bucket rate limiting algorithm.
        
        Args:
            key: Rate limit key (usually user/client identifier)
            capacity: Maximum tokens in bucket
            refill_rate: Tokens added per window
            tokens_requested: Tokens needed for this request
            window: Time window in seconds
            
        Returns:
            (allowed, retry_after_seconds)
        """
        bucket_key = f"rate_limit:token_bucket:{key}"
        
        try:
            # Lua script for atomic token bucket operations
            lua_script = """
            local bucket_key = KEYS[1]
            local capacity = tonumber(ARGV[1])
            local refill_rate = tonumber(ARGV[2])
            local tokens_requested = tonumber(ARGV[3])
            local window = tonumber(ARGV[4])
            local now = tonumber(ARGV[5])
            
            local bucket = redis.call('HMGET', bucket_key, 'tokens', 'last_refill')
            local tokens = tonumber(bucket[1]) or capacity
            local last_refill = tonumber(bucket[2]) or now
            
            -- Calculate tokens to add based on time elapsed
            local time_elapsed = now - last_refill
            local tokens_to_add = math.floor(time_elapsed / window * refill_rate)
            tokens = math.min(capacity, tokens + tokens_to_add)
            
            if tokens >= tokens_requested then
                -- Allow request
                tokens = tokens - tokens_requested
                redis.call('HMSET', bucket_key, 
                    'tokens', tokens, 
                    'last_refill', now)
                redis.call('EXPIRE', bucket_key, window * 2)
                return {1, 0}  -- allowed, retry_after
            else
                -- Deny request
                redis.call('HMSET', bucket_key, 
                    'tokens', tokens, 
                    'last_refill', now)
                redis.call('EXPIRE', bucket_key, window * 2)
                
                local retry_after = math.ceil((tokens_requested - tokens) / refill_rate * window)
                return {0, retry_after}  -- not allowed, retry_after
            end
            """
            
            current_time = int(time.time())
            
            result = await self.client.eval(
                lua_script, 1, bucket_key,
                capacity, refill_rate, tokens_requested, window, current_time
            )
            
            allowed = bool(result[0])
            retry_after = int(result[1])
            
            if not allowed:
                logger.debug(
                    "Token bucket rate limit exceeded",
                    key=key,
                    retry_after=retry_after
                )
            
            return allowed, retry_after
            
        except Exception as e:
            logger.error("Token bucket rate limiting failed", key=key, error=str(e))
            # Fail open for robustness
            return True, 0
    
    async def check_sliding_window(
        self,
        key: str,
        limit: int,
        window: int
    ) -> Tuple[bool, int]:
        """
        Sliding window counter rate limiting.
        
        Args:
            key: Rate limit key
            limit: Maximum requests per window
            window: Time window in seconds
            
        Returns:
            (allowed, retry_after_seconds)
        """
        rate_key = f"rate_limit:sliding_window:{key}"
        
        try:
            # Lua script for sliding window
            lua_script = """
            local rate_key = KEYS[1]
            local limit = tonumber(ARGV[1])
            local window = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])
            local window_start = now - window
            
            -- Remove old entries
            redis.call('ZREMRANGEBYSCORE', rate_key, 0, window_start)
            
            -- Count current requests
            local current_count = redis.call('ZCARD', rate_key)
            
            if current_count < limit then
                -- Allow request
                redis.call('ZADD', rate_key, now, now .. ':' .. math.random())
                redis.call('EXPIRE', rate_key, window)
                return {1, 0}
            else
                -- Deny request
                local oldest_request = redis.call('ZRANGE', rate_key, 0, 0, 'WITHSCORES')
                local retry_after = 0
                if next(oldest_request) then
                    retry_after = math.ceil(tonumber(oldest_request[2]) + window - now)
                end
                return {0, retry_after}
            end
            """
            
            current_time = int(time.time())
            
            result = await self.client.eval(
                lua_script, 1, rate_key,
                limit, window, current_time
            )
            
            allowed = bool(result[0])
            retry_after = int(result[1])
            
            if not allowed:
                logger.debug(
                    "Sliding window rate limit exceeded",
                    key=key,
                    retry_after=retry_after
                )
            
            return allowed, retry_after
            
        except Exception as e:
            logger.error("Sliding window rate limiting failed", key=key, error=str(e))
            return True, 0
    
    async def check_fixed_window(
        self,
        key: str,
        limit: int,
        window: int
    ) -> Tuple[bool, int]:
        """
        Fixed window counter rate limiting.
        
        Args:
            key: Rate limit key
            limit: Maximum requests per window
            window: Time window in seconds
            
        Returns:
            (allowed, retry_after_seconds)
        """
        current_time = int(time.time())
        window_key = f"rate_limit:fixed_window:{key}:{current_time // window}"
        
        try:
            # Lua script for atomic increment and check
            lua_script = """
            local window_key = KEYS[1]
            local limit = tonumber(ARGV[1])
            local window = tonumber(ARGV[2])
            local current_time = tonumber(ARGV[3])
            
            local current_count = redis.call('INCR', window_key)
            redis.call('EXPIRE', window_key, window)
            
            if current_count <= limit then
                return {1, 0}  -- allowed
            else
                local window_start = math.floor(current_time / window) * window
                local retry_after = window_start + window - current_time
                return {0, retry_after}  -- not allowed
            end
            """
            
            result = await self.client.eval(
                lua_script, 1, window_key,
                limit, window, current_time
            )
            
            allowed = bool(result[0])
            retry_after = int(result[1])
            
            if not allowed:
                logger.debug(
                    "Fixed window rate limit exceeded",
                    key=key,
                    retry_after=retry_after
                )
            
            return allowed, retry_after
            
        except Exception as e:
            logger.error("Fixed window rate limiting failed", key=key, error=str(e))
            return True, 0


# Global rate limiter instance
rate_limiter = RateLimiter()

# =============================================================================
# Distributed Lock Manager
# =============================================================================

class DistributedLock:
    """
    Redis-based distributed lock with automatic renewal and deadlock prevention.
    """
    
    def __init__(
        self,
        client: redis.Redis = redis_client,
        key: str = "",
        timeout: int = 30,
        blocking_timeout: Optional[int] = None,
        thread_local: bool = True
    ):
        self.client = client
        self.key = f"lock:{key}"
        self.timeout = timeout
        self.blocking_timeout = blocking_timeout
        self.thread_local = thread_local
        
        # Generate unique lock identifier
        self.identifier = f"{id(self)}:{time.time()}"
        self._acquired = False
    
    async def acquire(self) -> bool:
        """Acquire the distributed lock."""
        try:
            # Try to acquire lock
            if self.blocking_timeout is None:
                # Non-blocking acquire
                result = await self.client.set(
                    self.key,
                    self.identifier,
                    nx=True,  # Only set if doesn't exist
                    ex=self.timeout  # Set expiration
                )
                self._acquired = bool(result)
                
            else:
                # Blocking acquire with timeout
                end_time = time.time() + self.blocking_timeout
                
                while time.time() < end_time:
                    result = await self.client.set(
                        self.key,
                        self.identifier,
                        nx=True,
                        ex=self.timeout
                    )
                    
                    if result:
                        self._acquired = True
                        break
                    
                    # Wait before retry
                    await asyncio.sleep(0.1)
            
            if self._acquired:
                logger.debug("Distributed lock acquired", key=self.key)
            else:
                logger.debug("Failed to acquire distributed lock", key=self.key)
            
            return self._acquired
            
        except Exception as e:
            logger.error("Lock acquisition failed", key=self.key, error=str(e))
            return False
    
    async def release(self) -> bool:
        """Release the distributed lock."""
        if not self._acquired:
            return True
        
        try:
            # Lua script to ensure we only delete our own lock
            lua_script = """
            local lock_key = KEYS[1]
            local identifier = ARGV[1]
            
            if redis.call('GET', lock_key) == identifier then
                return redis.call('DEL', lock_key)
            else
                return 0
            end
            """
            
            result = await self.client.eval(lua_script, 1, self.key, self.identifier)
            
            if result:
                self._acquired = False
                logger.debug("Distributed lock released", key=self.key)
                return True
            else:
                logger.warning("Lock was already released or expired", key=self.key)
                return False
                
        except Exception as e:
            logger.error("Lock release failed", key=self.key, error=str(e))
            return False
    
    async def renew(self, new_timeout: Optional[int] = None) -> bool:
        """Renew the lock timeout."""
        if not self._acquired:
            return False
        
        timeout = new_timeout or self.timeout
        
        try:
            lua_script = """
            local lock_key = KEYS[1]
            local identifier = ARGV[1]
            local timeout = tonumber(ARGV[2])
            
            if redis.call('GET', lock_key) == identifier then
                return redis.call('EXPIRE', lock_key, timeout)
            else
                return 0
            end
            """
            
            result = await self.client.eval(
                lua_script, 1, self.key, self.identifier, timeout
            )
            
            success = bool(result)
            if success:
                logger.debug("Lock renewed", key=self.key, timeout=timeout)
            
            return success
            
        except Exception as e:
            logger.error("Lock renewal failed", key=self.key, error=str(e))
            return False
    
    async def __aenter__(self):
        """Async context manager entry."""
        if await self.acquire():
            return self
        else:
            raise LockAcquisitionError(f"Could not acquire lock: {self.key}")
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.release()


@asynccontextmanager
async def distributed_lock(
    key: str,
    timeout: int = 30,
    blocking_timeout: Optional[int] = None
):
    """Context manager for distributed locks."""
    lock = DistributedLock(
        key=key,
        timeout=timeout,
        blocking_timeout=blocking_timeout
    )
    
    async with lock:
        yield lock


# =============================================================================
# Session Management
# =============================================================================

class SessionManager:
    """Redis-based session management for web interfaces."""
    
    def __init__(self, client: redis.Redis = redis_session_client):
        self.client = client
        self.prefix = "session"
        self.default_ttl = 3600  # 1 hour
    
    def _make_key(self, session_id: str) -> str:
        """Generate session key."""
        return f"{self.prefix}:{session_id}"
    
    async def create_session(
        self,
        session_id: str,
        data: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> bool:
        """Create a new session."""
        try:
            session_key = self._make_key(session_id)
            session_data = {
                "created_at": time.time(),
                "data": json.dumps(data, default=str),
            }
            
            ttl = ttl or self.default_ttl
            
            result = await self.client.hmset(session_key, session_data)
            await self.client.expire(session_key, ttl)
            
            logger.debug("Session created", session_id=session_id, ttl=ttl)
            return bool(result)
            
        except Exception as e:
            logger.error("Session creation failed", session_id=session_id, error=str(e))
            return False
    
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data."""
        try:
            session_key = self._make_key(session_id)
            session_data = await self.client.hgetall(session_key)
            
            if not session_data:
                return None
            
            # Parse session data
            data = json.loads(session_data.get("data", "{}"))
            created_at = float(session_data.get("created_at", 0))
            
            return {
                "data": data,
                "created_at": datetime.fromtimestamp(created_at, tz=timezone.utc),
            }
            
        except Exception as e:
            logger.error("Session retrieval failed", session_id=session_id, error=str(e))
            return None
    
    async def update_session(
        self,
        session_id: str,
        data: Dict[str, Any],
        extend_ttl: bool = True
    ) -> bool:
        """Update session data."""
        try:
            session_key = self._make_key(session_id)
            
            # Update data
            result = await self.client.hset(
                session_key,
                "data",
                json.dumps(data, default=str)
            )
            
            # Extend TTL if requested
            if extend_ttl:
                await self.client.expire(session_key, self.default_ttl)
            
            logger.debug("Session updated", session_id=session_id)
            return bool(result)
            
        except Exception as e:
            logger.error("Session update failed", session_id=session_id, error=str(e))
            return False
    
    async def delete_session(self, session_id: str) -> bool:
        """Delete session."""
        try:
            session_key = self._make_key(session_id)
            result = await self.client.delete(session_key)
            
            logger.debug("Session deleted", session_id=session_id)
            return bool(result)
            
        except Exception as e:
            logger.error("Session deletion failed", session_id=session_id, error=str(e))
            return False
    
    async def extend_session(self, session_id: str, ttl: Optional[int] = None) -> bool:
        """Extend session TTL."""
        try:
            session_key = self._make_key(session_id)
            ttl = ttl or self.default_ttl
            
            result = await self.client.expire(session_key, ttl)
            
            if result:
                logger.debug("Session extended", session_id=session_id, ttl=ttl)
            
            return bool(result)
            
        except Exception as e:
            logger.error("Session extension failed", session_id=session_id, error=str(e))
            return False


# Global session manager
session_manager = SessionManager()

# =============================================================================
# Convenience Functions and Decorators
# =============================================================================

async def check_rate_limit(
    client_id: str,
    resource: str = "default",
    limit: int = 100,
    window: int = 3600,
    algorithm: str = "sliding_window"
) -> None:
    """
    Convenience function for rate limiting checks.
    
    Raises RateLimitExceeded if limit exceeded.
    """
    key = f"{client_id}:{resource}"
    
    if algorithm == "sliding_window":
        allowed, retry_after = await rate_limiter.check_sliding_window(key, limit, window)
    elif algorithm == "fixed_window":
        allowed, retry_after = await rate_limiter.check_fixed_window(key, limit, window)
    elif algorithm == "token_bucket":
        allowed, retry_after = await rate_limiter.check_token_bucket(
            key, capacity=limit, refill_rate=limit//10, window=window
        )
    else:
        raise ValueError(f"Unknown rate limiting algorithm: {algorithm}")
    
    if not allowed:
        raise RateLimitExceeded(
            f"Rate limit exceeded for {resource}. Try again in {retry_after} seconds.",
            retry_after=retry_after
        )


def cached(
    ttl: int = 3600,
    namespace: str = "",
    key_func: Optional[Callable] = None,
    tags: Optional[List[str]] = None
):
    """
    Decorator for caching function results.
    
    Args:
        ttl: Time to live in seconds
        namespace: Cache namespace
        key_func: Function to generate cache key
        tags: Tags for grouped invalidation
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # Default key generation
                key_parts = [func.__name__]
                key_parts.extend(str(arg) for arg in args)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                key_str = ":".join(key_parts)
                cache_key = hashlib.md5(key_str.encode()).hexdigest()
            
            # Try to get from cache
            cached_result = await cache.get(cache_key, namespace)
            if cached_result is not None:
                return cached_result
            
            # Execute function and cache result
            result = await func(*args, **kwargs)
            await cache.set(cache_key, result, ttl, namespace, tags)
            
            return result
        
        return wrapper
    return decorator


# =============================================================================
# Health Checks and Monitoring
# =============================================================================

async def redis_health_check() -> Dict[str, Any]:
    """Check Redis connection health."""
    health_info = {
        "redis_main": {"status": "unknown", "error": None},
        "redis_queue": {"status": "unknown", "error": None},
        "redis_session": {"status": "unknown", "error": None},
    }
    
    # Test main Redis
    try:
        await redis_client.ping()
        info = await redis_client.info("server")
        health_info["redis_main"] = {
            "status": "healthy",
            "version": info.get("redis_version", "unknown"),
            "uptime": info.get("uptime_in_seconds", 0),
        }
    except Exception as e:
        health_info["redis_main"] = {
            "status": "unhealthy",
            "error": str(e),
        }
    
    # Test queue Redis
    try:
        await redis_queue_client.ping()
        health_info["redis_queue"] = {"status": "healthy"}
    except Exception as e:
        health_info["redis_queue"] = {
            "status": "unhealthy",
            "error": str(e),
        }
    
    # Test session Redis
    try:
        await redis_session_client.ping()
        health_info["redis_session"] = {"status": "healthy"}
    except Exception as e:
        health_info["redis_session"] = {
            "status": "unhealthy",
            "error": str(e),
        }
    
    return health_info


# =============================================================================
# Cleanup and Shutdown
# =============================================================================

async def close_redis_connections():
    """Close all Redis connections gracefully."""
    try:
        await redis_client.close()
        await redis_queue_client.close()
        await redis_session_client.close()
        logger.info("All Redis connections closed")
    except Exception as e:
        logger.error("Error closing Redis connections", error=str(e))


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "redis_client",
    "redis_queue_client", 
    "redis_queue_sync",
    "redis_session_client",
    "cache",
    "rate_limiter",
    "session_manager",
    "CacheManager",
    "RateLimiter",
    "SessionManager",
    "DistributedLock",
    "distributed_lock",
    "check_rate_limit",
    "cached",
    "redis_health_check",
    "close_redis_connections",
    "RateLimitExceeded",
    "CacheError",
    "LockAcquisitionError",
]
