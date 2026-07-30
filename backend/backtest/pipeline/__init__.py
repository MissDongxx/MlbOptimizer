"""Auditable history-validation and candidate-model automation.

Import concrete modules directly to keep the backtest runner free of orchestration cycles.
"""

from backtest.pipeline.config import PipelineConfig

__all__ = ["PipelineConfig"]
