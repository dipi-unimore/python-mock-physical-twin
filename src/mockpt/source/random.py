from typing import Literal, Optional, List, Any, Dict
from scipy import stats
from dataclasses import dataclass

from mockpt.source.base import SourceBase, SourceBaseConfig


class RandomSourceConfig(SourceBaseConfig):
    type: Literal["random"] = "random" # type: ignore
    rv: str
    rv_params: Optional[Dict[str, Any]] = None
    max: Optional[float] = None
    min: Optional[float] = None
    step: Optional[float] = None


@dataclass
class RandomSource(SourceBase):
    config: RandomSourceConfig # type: ignore
    
    def __post_init__(self):
        super().__post_init__()

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

    def _next(self):

        value = self._apply_modifiers(
            self.distribution.rvs(),
            min_val=self.config.min,
            max_val=self.config.max,
            step=self.config.step
        )

        return {
            "value": value
        }
    

if __name__ == "__main__":
    config = RandomSourceConfig(
        type="random",
        rv="norm",
    )

    source = RandomSource(
        identifier="temperature",
        eventbus_client=None, # type: ignore
        config=config,
    )

    for _ in range(10):
        print(source._next())