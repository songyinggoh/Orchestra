"""Secret storage abstraction for agent key material."""

from __future__ import annotations
import abc
import asyncio
from typing import Any
from orchestra.identity.types import SecretProvider

class InMemorySecretProvider:
    """In-memory secret store for testing and local development."""
    def __init__(self) -> None:
        self._secrets: dict[str, bytes] = {}

    async def get_secret(self, path: str) -> bytes:
        if path not in self._secrets:
            raise KeyError(f"Secret not found at path: {path}")
        return self._secrets[path]

    async def put_secret(self, path: str, value: bytes) -> None:
        self._secrets[path] = value

    async def delete_secret(self, path: str) -> None:
        if path in self._secrets:
            del self._secrets[path]

class VaultSecretProvider:
    """HashiCorp Vault KV v2 backend.
    
    Requires hvac library. Not fully implemented in this prototype.
    """
    def __init__(self, url: str, token: str, mount_point: str = "secret") -> None:
        self.url = url
        self.token = token
        self.mount_point = mount_point
        self._client = None # lazy load

    def _get_client(self):
        if self._client is None:
            import hvac
            self._client = hvac.Client(url=self.url, token=self.token)
        return self._client

    async def get_secret(self, path: str) -> bytes:
        client = self._get_client()
        # Mocking async behavior via thread pool for blocking hvac calls
        response = await asyncio.to_thread(
            client.secrets.kv.v2.read_secret_version,
            path=path, mount_point=self.mount_point
        )
        data = response["data"]["data"]["value"]
        import base64
        return base64.b64decode(data)

    async def put_secret(self, path: str, value: bytes) -> None:
        client = self._get_client()
        import base64
        data = {"value": base64.b64encode(value).decode()}
        await asyncio.to_thread(
            client.secrets.kv.v2.create_or_update_secret_version,
            path=path, secret=data, mount_point=self.mount_point
        )

    async def delete_secret(self, path: str) -> None:
        client = self._get_client()
        await asyncio.to_thread(
            client.secrets.kv.v2.delete_latest_version_of_secret,
            path=path, mount_point=self.mount_point
        )
