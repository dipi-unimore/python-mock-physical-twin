import asyncio
from typing import Optional
from dataclasses import dataclass, field

from mockpt.common.message.data_message import DataMessage


@dataclass(kw_only=True)
class Stream:
    interval: Optional[float] = None
    last_value: Optional[DataMessage] = None

    _value_updated: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _running: bool = field(default=False, init=False)
    _inner_loop_task: Optional[asyncio.Task] = field(default=None, init=False)

    def __post_init__(self):
        self._value_updated.clear()

    def put(self, value: DataMessage):
        self.last_value = value
        self._value_updated.set()

    async def start(self):
        self._running = True
        self._inner_loop_task = asyncio.create_task(self._inner_loop())

    async def stop(self):
        self._running = False
        if self._inner_loop_task is not None:
            self._inner_loop_task.cancel()

    async def _inner_loop(self):
        if self.interval is not None:
            await self._value_updated.wait()    # await only first value, then loop with fixed interval

            while self._running:
                self._value_updated.clear()
                await asyncio.sleep(self.interval)

                print(f"New value: {self.last_value}")
        else:
            while self._running:
                await self._value_updated.wait()
                self._value_updated.clear()

                print(f"New value: {self.last_value}")