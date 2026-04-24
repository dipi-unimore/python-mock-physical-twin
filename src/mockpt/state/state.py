import asyncio
from dataclasses import dataclass, field
from typing import Optional

from mockpt.common.message.data_message import DataMessage
from mockpt.state.identity_logic import IdentityStateLogic
from mockpt.state.logic import StateLogic


@dataclass(kw_only=True)
class State:
    logic: StateLogic
    queue: asyncio.Queue[DataMessage] = field(default_factory=lambda: asyncio.Queue(maxsize=1), init=False)
    
    async def put(self, value: DataMessage):
        
        value = self.logic.process(value)
        
        # TODO:
        # - More pervasive way to modify state from logic class
        # - Init params for logic class from yaml
        # - Pre-define some logic classes (e.g. identity, delay, corruption by dev, loss, chaotic with all previous etc.); for delay maybe use a sleep before queue.put
        
    
        await self.queue.put(value)
            
        