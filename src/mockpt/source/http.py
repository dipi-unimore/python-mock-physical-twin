from typing import Literal, Optional
from dataclasses import dataclass, field
import asyncio
from aiohttp import web

from mockpt.source.base import SourceBase, SourceBaseConfig
from mockpt.source.enum import SourceName


class HttpSourceConfig(SourceBaseConfig):
    type: Literal[SourceName.HTTP.value] = SourceName.HTTP.value # type: ignore
    path: str
    method: Literal["GET", "POST", "PUT", "DELETE"] = "POST"
    host: str = "0.0.0.0"
    port: int = 8080
    content_type: Optional[str] = None
    # TODO: scegliere codice di risposta OK
    # TODO: informazioni per gestire la risposta FAIL


@dataclass
class HttpSource(SourceBase):
    config: HttpSourceConfig  # type: ignore
    _runner: web.AppRunner = field(init=False)
    _site: web.TCPSite = field(init=False)
    _queue: asyncio.Queue = field(default_factory=asyncio.Queue, init=False)
    # TODO: response queue

    async def _handle_request(self, request: web.Request) -> web.Response:
        
        if self.config.content_type:
            if request.content_type != self.config.content_type:
                return web.Response(status=400, text=f"Invalid content type. Expected {self.config.content_type}")
        
        payload = await request.text()
        
        # TODO: sostituire con push verso device e attesa risposta
        await self._queue.put(payload)
        
        # TODO: await response queue
        
        # TODO: gestire risposta OK/FAIL
        return web.Response(status=200, text="OK")

    async def _on_starting(self, *args, **kwargs):
        await super()._on_starting(*args, **kwargs)
        
        app = web.Application()
        app.router.add_route(
            self.config.method, 
            self.config.path, 
            self._handle_request
        )
        
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        
        self._site = web.TCPSite(
            self._runner, 
            self.config.host, 
            self.config.port
        )
        await self._site.start()
        
    async def _on_stopping(self, *args, **kwargs):
        if hasattr(self, '_runner') and self._runner:
            await self._runner.cleanup()
            
        await super()._on_stopping(*args, **kwargs)

    async def _datastream(self):
        while True:
            payload = await self._queue.get()
            yield {
                "value": payload
            }