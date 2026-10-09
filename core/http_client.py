"""Shared HTTP client with timeouts, retries, and connection pooling."""
import asyncio
import logging
from typing import Optional, Dict, Any
import aiohttp
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
    before_sleep_log,
)

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = aiohttp.ClientTimeout(
    total=30.0,
    connect=10.0,
    sock_read=20.0,
    sock_connect=10.0,
)

DEFAULT_RETRY_CONFIG = dict(
    wait=wait_exponential_jitter(initial=1.0, max=10.0),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
    before_sleep=before_sleep_log(log, logging.WARNING),
)


class HttpClient:
    """Async HTTP client with configurable timeouts, retries, and connection pooling."""

    def __init__(
        self,
        timeout: Optional[aiohttp.ClientTimeout] = None,
        retry_config: Optional[Dict[str, Any]] = None,
        connector: Optional[aiohttp.TCPConnector] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._retry_config = retry_config or DEFAULT_RETRY_CONFIG
        self._connector = connector or aiohttp.TCPConnector(
            limit=10,
            limit_per_host=5,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
        )
        self._default_headers = headers or {}
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "HttpClient":
        self._session = aiohttp.ClientSession(
            timeout=self._timeout,
            connector=self._connector,
            headers=self._default_headers,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session and not self._session.closed:
            await self._session.close()

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            raise RuntimeError("HttpClient not initialized. Use async with or call start().")
        return self._session

    async def start(self):
        """Start the client session (alternative to async with)."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                connector=self._connector,
                headers=self._default_headers,
            )

    async def close(self):
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()

    @retry(**DEFAULT_RETRY_CONFIG)
    async def _request_with_retry(self, method: str, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Execute request with retry logic."""
        return await self.session.request(method, url, **kwargs)

    async def get(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """GET request with retries."""
        return await self._request_with_retry("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """POST request with retries."""
        return await self._request_with_retry("POST", url, **kwargs)

    async def request(self, method: str, url: str, **kwargs) -> aiohttp.ClientResponse:
        """Generic request with retries."""
        return await self._request_with_retry(method, url, **kwargs)

    async def get_json(self, url: str, **kwargs) -> Any:
        """GET request expecting JSON response."""
        async with await self.get(url, **kwargs) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def post_json(self, url: str, **kwargs) -> Any:
        """POST request expecting JSON response."""
        async with await self.post(url, **kwargs) as resp:
            resp.raise_for_status()
            return await resp.json()


async def quick_get(
    url: str,
    timeout: Optional[aiohttp.ClientTimeout] = None,
    **kwargs
) -> str:
    """Quick one-off GET request returning text."""
    async with HttpClient(timeout=timeout) as client:
        async with await client.get(url, **kwargs) as resp:
            resp.raise_for_status()
            return await resp.text()


async def quick_post(
    url: str,
    data: Any = None,
    json: Any = None,
    timeout: Optional[aiohttp.ClientTimeout] = None,
    **kwargs
) -> str:
    """Quick one-off POST request returning text."""
    async with HttpClient(timeout=timeout) as client:
        async with await client.post(url, data=data, json=json, **kwargs) as resp:
            resp.raise_for_status()
            return await resp.text()