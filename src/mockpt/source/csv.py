import asyncio
import logging
from typing import Any, Dict, Literal, Optional, List, override
import pandas as pd
from dataclasses import dataclass, field

from mockpt.source.base import SourceBase, SourceBaseConfig
from mockpt.source.datastream_mixin import DataStreamMixin
from mockpt.source.enum import SourceName


class CsvSourceConfig(SourceBaseConfig):
    type: Literal[SourceName.CSV.value] = SourceName.CSV.value # type: ignore
    file: str
    columns: Optional[List[str]] = None
    timestamp_column: Optional[str] = None
    rotate: bool = True
    interval: Optional[float] = None


@dataclass
class CsvSource(DataStreamMixin, SourceBase):
    config: CsvSourceConfig # type: ignore
    data: pd.DataFrame = field(init=False)
    index: int = field(default=0, init=False)
    __datastream_task: Optional[asyncio.Task] = field(default=None, init=False)
    
    def __post_init__(self):
        super().__post_init__()
            
        self.data = pd.read_csv(self.config.file)
        
        if self.config.timestamp_column and self.config.timestamp_column not in self.data.columns:
            raise ValueError(f"Timestamp column '{self.config.timestamp_column}' not found in CSV file.")
        
        if self.config.interval is not None and self.config.interval <= 0:
            raise ValueError("Interval must be a positive number.")
        
        if self.config.interval is None and self.config.timestamp_column is None:
            raise ValueError("Either 'interval' or 'timestamp_column' must be specified.")
    
    @override
    async def _datastream(self):
        while True:
            if self.index >= len(self.data):
                if not self.config.rotate:
                    raise StopIteration
                else:
                    self.index = 0

            row = self.data.iloc[self.index]
            self.index += 1

            if self.config.columns is None:
                result: Dict[str, Any] = row.to_dict() # type: ignore
            else:
                cols = set(self.config.columns)
                
                if self.config.timestamp_column:
                    cols.add(self.config.timestamp_column)
                
                result = {str(col): row[col] for col in sorted(cols)}

            await self._data_queue.put(result)
            
            if self.config.interval is not None:
                await asyncio.sleep(self.config.interval)
            else:
                assert self.config.timestamp_column is not None, "Timestamp column must be specified if interval is not set."
                
                current_timestamp = pd.to_datetime(result[self.config.timestamp_column])
                
                if self.index < len(self.data):
                    next_timestamp = pd.to_datetime(self.data.iloc[self.index][self.config.timestamp_column])
                    delay = (next_timestamp - current_timestamp).total_seconds()
                    
                    if delay > 0:
                        await asyncio.sleep(delay)
                    else:
                        logging.warning(f"Non-positive delay of {delay} seconds between timestamps at index {self.index-1} and {self.index}. Skipping sleep.")
    
