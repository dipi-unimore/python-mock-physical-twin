from typing import Any, Dict, Literal, Optional, List
import pandas as pd
from dataclasses import dataclass, field

from mockpt.source.base import SourceBase, SourceBaseConfig


class CsvSourceConfig(SourceBaseConfig):
    type: Literal["csv"] = "csv" # type: ignore
    file: str
    columns: Optional[List[str]] = None
    timestamp_column: Optional[str] = None
    interval: Optional[int] = None  # in milliseconds
    rotate: bool = True


@dataclass
class CsvSource(SourceBase):
    config: CsvSourceConfig # type: ignore
    data: pd.DataFrame = field(init=False)
    index: int = field(default=0, init=False)
    
    def __post_init__(self):
        super().__post_init__()
    
        self.data = pd.read_csv(self.config.file)
    
    async def _next(self) -> Dict[str, Any]:
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

        return result
    
