from abc import ABC, abstractmethod
import asyncio
from typing import override

from mockpt.source.base import SourceBase


class DataStreamMixin(SourceBase, ABC):
    @override
    async def turn_on_datastream(self):
        await super().turn_on_datastream()
    
        self.__datastream_task = asyncio.create_task(self._datastream())
    
    @override
    async def turn_off_datastream(self):
        await super().turn_off_datastream()
        
        if self.__datastream_task:
            self._datastream_turn_off.set()    # signal the datastream to stop
            await self.__datastream_task
            
    @abstractmethod
    async def _datastream(self):
        pass