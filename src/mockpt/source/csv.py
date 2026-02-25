from typing import Literal, Optional, List
import pandas as pd

from source.base import SourceBase, SourceBaseConfig


class CsvSourceConfig(SourceBaseConfig):
    type: Literal["csv"] = "csv" # type: ignore
    file: str
    columns: List[str]
    timestamp_column: Optional[str] = None
    interval: Optional[int] = None  # in milliseconds


class CsvSource(SourceBase):
    def __init__(self, config: CsvSourceConfig):
        super().__init__(config)

        self.config = config
        self.data = pd.read_csv(config.file)
        self.index = 0

    def next(self):
        if self.index >= len(self.data):
            raise StopIteration

        row = self.data.iloc[self.index]
        self.index += 1

        result = {col: row[col] for col in self.config.columns}

        if self.config.timestamp_column:
            result["timestamp"] = row[self.config.timestamp_column]

        return result
    
