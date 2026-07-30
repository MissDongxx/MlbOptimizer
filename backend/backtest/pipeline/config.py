from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backtest.io import load_json


@dataclass(frozen=True)
class PipelineConfig:
    root_dir: Path
    inbox_dir: Path
    artifact_dir: Path
    registry_path: Path
    statsapi_cache_dir: Path
    backtest_dir: Path
    dataset_dir: Path
    model_dir: Path
    report_dir: Path
    offline: bool = False
    retries: int = 3
    timeout_seconds: float = 20.0
    seed: int = 20260730
    lineups_per_method: int = 5
    min_backtest_real_slates: int = 30
    bootstrap_samples: int = 2000
    min_train_slates: int = 20
    min_test_slates: int = 5
    min_test_rows_per_role: int = 100
    test_fraction: float = 0.20
    ridge_alpha: float = 10.0
    required_mae_relative_improvement: float = 0.0
    max_rmse_relative_regression: float = 0.0
    max_correlation_drop: float = 0.01
    code_version: str = "working-tree-uncommitted"

    @classmethod
    def from_json(cls, path: Path) -> "PipelineConfig":
        raw = load_json(path)
        if not isinstance(raw, dict):
            raise ValueError("pipeline config must be a JSON object")
        base = path.resolve().parent
        root = _resolve(base, raw.get("root_dir", "."))
        values: dict[str, Any] = dict(raw)
        values["root_dir"] = root
        defaults = {
            "inbox_dir": "inbox",
            "artifact_dir": "artifacts",
            "registry_path": "catalog/registry.json",
            "statsapi_cache_dir": "cache/statsapi",
            "backtest_dir": "backtests",
            "dataset_dir": "datasets",
            "model_dir": "models",
            "report_dir": "reports",
        }
        for key, default in defaults.items():
            values[key] = _resolve(root, raw.get(key, default))
        config = cls(**values)
        config.validate()
        return config

    def validate(self) -> None:
        if self.retries < 1:
            raise ValueError("retries must be at least 1")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not 1 <= self.lineups_per_method <= 20:
            raise ValueError("lineups_per_method must be between 1 and 20")
        if self.min_backtest_real_slates < 1:
            raise ValueError("min_backtest_real_slates must be positive")
        if self.bootstrap_samples < 1:
            raise ValueError("bootstrap_samples must be positive")
        if self.min_train_slates < 1 or self.min_test_slates < 1:
            raise ValueError("model slate thresholds must be positive")
        if self.min_test_rows_per_role < 1:
            raise ValueError("min_test_rows_per_role must be positive")
        if not 0 < self.test_fraction < 0.5:
            raise ValueError("test_fraction must be in (0, 0.5)")
        if self.ridge_alpha < 0:
            raise ValueError("ridge_alpha must be non-negative")
        if self.required_mae_relative_improvement < -1:
            raise ValueError("required_mae_relative_improvement must be >= -1")
        if self.max_rmse_relative_regression < 0:
            raise ValueError("max_rmse_relative_regression must be non-negative")
        if self.max_correlation_drop < 0:
            raise ValueError("max_correlation_drop must be non-negative")

    def ensure_directories(self) -> None:
        for directory in (
            self.root_dir,
            self.inbox_dir,
            self.artifact_dir,
            self.registry_path.parent,
            self.statsapi_cache_dir,
            self.backtest_dir,
            self.dataset_dir,
            self.model_dir,
            self.report_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _resolve(base: Path, value: object) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()
