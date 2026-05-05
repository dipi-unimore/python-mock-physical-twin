import asyncio
import logging
from typing import Any, Dict, Literal, Optional, List, Union, override
import pandas as pd
from dataclasses import dataclass, field

from mockpt.source.base import SourceBase, SourceBaseConfig
from mockpt.source.datastream_mixin import DataStreamMixin
from mockpt.source.enum import SourceName


class CsvSourceConfig(SourceBaseConfig):
    type: Literal[SourceName.CSV.value] = SourceName.CSV.value # type: ignore
    files: Union[str, List[str]]
    columns: Optional[List[str]] = None
    timestamp_column: Optional[str] = None
    timestamp_format: Optional[str] = None
    rotate: bool = True
    interval: Optional[float] = None


@dataclass
class CsvSource(DataStreamMixin, SourceBase):
    config: CsvSourceConfig # type: ignore
    data: pd.DataFrame = field(init=False)
    index: int = field(default=0, init=False)
    
    def __post_init__(self):
        super().__post_init__()
            
        # 1. Configuration Validation
        if self.config.interval is not None and self.config.interval <= 0:
            raise ValueError("Interval must be a positive number.")
        
        if self.config.interval is None and self.config.timestamp_column is None:
            raise ValueError("Either 'interval' or 'timestamp_column' must be specified.")

        # 2. Load DataFrames and Validate Columns
        file_paths = [self.config.files] if isinstance(self.config.files, str) else self.config.files
        if not file_paths:
            raise ValueError("At least one CSV file must be specified.")

        dfs = [pd.read_csv(f) for f in file_paths]
        
        # Check for column mismatch across multiple files
        if len(dfs) > 1:
            base_columns = set(dfs[0].columns)
            for i, df_part in enumerate(dfs[1:], start=1):
                if set(df_part.columns) != base_columns:
                    raise ValueError(
                        f"Schema mismatch detected: columns in '{file_paths[i]}' "
                        f"do not match the columns in '{file_paths[0]}'."
                    )

        # Merge DataFrames (pd.concat naturally appends sequentially in the provided order)
        df = pd.concat(dfs, ignore_index=True)
        
        if self.config.timestamp_column and self.config.timestamp_column not in df.columns:
            raise ValueError(f"Timestamp column '{self.config.timestamp_column}' not found in CSV files.")
            
        # 3. Sort by timestamp or keep sequential
        if self.config.timestamp_column:
            df[self.config.timestamp_column] = pd.to_datetime(
                df[self.config.timestamp_column], 
                format=self.config.timestamp_format
            )
            df = df.sort_values(by=self.config.timestamp_column).reset_index(drop=True)
        elif len(file_paths) > 1:
            # Files remain sequential based on how they were passed
            logging.info("No timestamp_column specified. Files are merged sequentially in the order they were passed.")

        # 4. Pre-filter columns for clean and fast output
        if self.config.columns is not None:
            cols_to_keep = set(self.config.columns)
            if self.config.timestamp_column:
                cols_to_keep.add(self.config.timestamp_column)
            
            valid_cols = [c for c in cols_to_keep if c in df.columns]
            df = df[valid_cols]

        # 5. Cache state and pre-compute records for O(1) iteration speed
        self.data = df
        self._records = self.data.to_dict(orient="records")
    
    @override
    async def _datastream(self):
        total_records = len(self._records)
        if total_records == 0:
            return

        while True:
            if self.index >= total_records:
                if not self.config.rotate:
                    return  # Cleaner exit for async coroutines than raising StopIteration
                else:
                    self.index = 0

            # Fetch the pre-computed dictionary
            result = self._records[self.index]
            self.index += 1
            
            message = result.copy()
            if self.config.timestamp_column and self.config.timestamp_column in result.keys():
                # Convert timestamp to ISO format string for consistent output
                message[self.config.timestamp_column] = message[self.config.timestamp_column].isoformat()

            await self._data_queue.put(message)
            
            # Handle Delays
            if self.config.interval is not None:
                await asyncio.sleep(self.config.interval)
            else:
                assert self.config.timestamp_column is not None, "Timestamp column must be specified if interval is not set."
                
                if self.index < total_records:
                    current_timestamp = result[self.config.timestamp_column]
                    next_timestamp = self._records[self.index][self.config.timestamp_column]
                    
                    delay = (next_timestamp - current_timestamp).total_seconds()
                    
                    if delay > 0:
                        await asyncio.sleep(delay)
                    else:
                        logging.warning(
                            f"Non-positive delay of {delay} seconds between timestamps at index {self.index-1} and {self.index}. Skipping sleep."
                        )