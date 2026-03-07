import logging
from typing import Literal, Optional, Dict
from dataclasses import dataclass, field
import aiohttp

from mockpt.destination.base import DestinationBase, DestinationBaseConfig
from mockpt.common.message.data_message import DataMessage
from mockpt.destination.enum import DestinationName


class HttpDestinationConfig(DestinationBaseConfig):
    type: Literal[DestinationName.HTTP.value] = DestinationName.HTTP.value # type: ignore
    base_url: str
    method: Literal["GET", "POST", "PUT", "DELETE"] = "POST"
    headers: Optional[Dict[str, str]] = None


@dataclass
class HttpDestination(DestinationBase):
    config: HttpDestinationConfig # type: ignore
    _session: Optional[aiohttp.ClientSession] = field(default=None, init=False)

    def __post_init__(self):
        super().__post_init__()

    async def _on_starting(self, *args, **kwargs):
        await super()._on_starting(*args, **kwargs)
        
        self._session = aiohttp.ClientSession(
            base_url=self.config.base_url,
            headers=self.config.headers
        )
        
    async def _on_stopping(self, *args, **kwargs):
        if self._session:
            await self._session.close()
            self._session = None
            
        await super()._on_stopping(*args, **kwargs)

    async def _send(self, endpoint: str, data: DataMessage):
        if self._session is None:
            raise RuntimeError("HTTP session is not initialized.")
        
        try:
            async with self._session.request(
                method=self.config.method,
                url=endpoint,
                data=data.json_value,
                headers={"Connection": "close"}
            ) as response:
                await response.read()
        except Exception as e:
            logging.error(f"Failed to send data to {endpoint}: {e}")