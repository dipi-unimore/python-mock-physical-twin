import asyncio
from typing import Literal, Optional, List, Any, Dict, override
from scipy import stats
from dataclasses import dataclass, field

from mockpt.source.base import SourceBase, SourceBaseConfig
from mockpt.source.datastream_mixin import DataStreamMixin
from mockpt.source.enum import SourceName


class RandomSourceConfig(SourceBaseConfig):
    type: Literal[SourceName.RANDOM.value] = SourceName.RANDOM.value # type: ignore
    rv: str
    interval: float
    rv_params: Optional[Dict[str, Any]] = None
    max: Optional[float] = None
    min: Optional[float] = None
    step: Optional[float] = None


@dataclass
class RandomSource(DataStreamMixin, SourceBase):
    config: RandomSourceConfig # type: ignore
    
    def __post_init__(self):
        super().__post_init__()
        
        if self.config.interval is not None and self.config.interval <= 0:
            raise ValueError("Interval must be a positive number.")
        
        # Extract parameters for the random variable
        rv_params = {}
        if self.config.rv_params:
            rv_params = self.config.rv_params
        
        try:
            # Get the distribution from scipy.stats
            self.distribution = getattr(stats, self.config.rv)(**rv_params)
        except AttributeError:
            raise ValueError(f"Invalid random variable name: {self.config.rv}")
        
    def _apply_modifiers(self, valore, min_val=None, max_val=None, step=None):
        
        if step is not None and step > 0:
            valore = round(valore / step) * step
        
        if max_val is not None:
            valore = min(valore, max_val)
            
        if min_val is not None:
            valore = max(valore, min_val)
            
        return valore
    
    @override
    async def _datastream(self):
        while self._datastream_turn_off.is_set() is False:
            value = self._apply_modifiers(
                self.distribution.rvs(),
                min_val=self.config.min,
                max_val=self.config.max,
                step=self.config.step
            )

            await self._data_queue.put({
                "value": float(value)
            })
            
            # response = await self._response_queue.get()    # wait for the response to be put in the queue by the device after processing the data
            
            await asyncio.sleep(self.config.interval)
    