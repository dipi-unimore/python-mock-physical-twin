from typing import Literal, Optional
from dataclasses import dataclass, field
import asyncio
from aiohttp import web

from mockpt.source.base import SourceBase, SourceBaseConfig
from mockpt.source.enum import SourceName


class HttpSourceConfig(SourceBaseConfig):
    type: Literal[SourceName.HTTP.value] = SourceName.HTTP.value # type: ignore
    path: str    
    host: str = "0.0.0.0"
    port: int = 8080
    content_type: Optional[str] = None
    method: Literal["GET", "POST", "PUT", "DELETE"] = "PUT"
    ok_response_code: int = 201
    fail_response_code: int = 412


@dataclass
class HttpSource(SourceBase):
    config: HttpSourceConfig  # type: ignore
    _runner: web.AppRunner = field(init=False)
    _site: web.TCPSite = field(init=False)
    
    
    @property
    def mandatory_response_handling(self) -> bool:
        return True


    async def _handle_request(self, request: web.Request) -> web.Response:
        
        if self.config.content_type:
            if request.content_type != self.config.content_type:
                return web.Response(status=400, text=f"Invalid content type. Expected {self.config.content_type}")
        
        payload = await request.text()
        
        assert self._data_queue.empty(), "Data queue is full, previous data not yet processed by the device"
        assert self._response_queue.empty(), "Response queue is full, previous response not yet processed by the device"
        
        await self._data_queue.put(payload)
        
        response = await self._response_queue.get()    # wait for the response to be put in the queue by the device after processing the data
        
        if response.success:
            return web.Response(status=self.config.ok_response_code, text=response.message)
        else:
            return web.Response(status=self.config.fail_response_code, text=response.message)

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
