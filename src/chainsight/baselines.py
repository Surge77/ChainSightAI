"""The numbers every model here has to beat, established before any model exists.

A baseline is not a formality. Without one, 0.70 accuracy sounds like a result; with one it
turns out to be what a single `if` statement already does. Three are defined:

**Majority** predicts the most common class, always. It scores 0.5483 on this table and is
the floor below which a classifier is worse than a coin weighted by the training set.

**Shipping-mode rule** predicts the majority class within each shipping mode. This is the
one that matters. It scores **0.6953**, and it is four lines of pandas. Any model in this
project that does not clear it is not earning its complexity, and one that clears it by a
wide margin should be checked for a leak before being believed.

**Mean margin** predicts the training mean for every order, giving 0.2941 MAE. Beating it
by a little is expected; beating it by a lot on this data would be surprising.

All three learn only from the frame they are fitted on, exactly as a model does, so the
comparison is fair rather than flattering.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from chainsight import schema

#: The rule baseline groups on this. Chosen because the audit measured a 0.5725 spread in
#: late rate across its four values, against 0.0010 for the weekend flag.
RULE_COLUMN = "Shipping Mode"

_MAJORITY_THRESHOLD = 0.5


@dataclass(frozen=True)
class MajorityClass:
    """Predict the training set's most common label, whatever the order says."""

    label: int

    @classmethod
    def fit(cls, frame: pd.DataFrame) -> MajorityClass:
        rate = frame[schema.LATE_TARGET].mean()
        return cls(label=int(rate > _MAJORITY_THRESHOLD))

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.full(len(frame), self.label, dtype="int64")


@dataclass(frozen=True)
class GroupRate:
    """Predict each group's training late rate, and label by whether it exceeds a half.

    The probability is the group's own rate rather than a hard 0 or 1, which is what makes
    this a fair comparison for a project whose decision engine consumes probability. A
    group unseen in training falls back to the overall training rate.
    """

    column: str
    rates: dict[str, float]
    fallback: float

    @classmethod
    def fit(cls, frame: pd.DataFrame, column: str = RULE_COLUMN) -> GroupRate:
        rates = frame.groupby(column)[schema.LATE_TARGET].mean()
        return cls(
            column=column,
            rates={str(key): float(value) for key, value in rates.items()},
            fallback=float(frame[schema.LATE_TARGET].mean()),
        )

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        mapped = frame[self.column].astype(str).map(self.rates).fillna(self.fallback)
        return mapped.to_numpy(dtype="float64")

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(frame) > _MAJORITY_THRESHOLD).astype("int64")


@dataclass(frozen=True)
class MeanValue:
    """Predict the training mean of the margin ratio for every order."""

    value: float

    @classmethod
    def fit(cls, frame: pd.DataFrame) -> MeanValue:
        return cls(value=float(frame[schema.MARGIN_TARGET].mean()))

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.full(len(frame), self.value)
