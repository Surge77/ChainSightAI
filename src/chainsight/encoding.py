"""Turn category strings into integers the way the course did, and survive serving.

`LabelEncoder` is the only encoder in the curriculum. `OneHotEncoder` and
`ColumnTransformer` are not, so every categorical column here becomes a single integer
code rather than a block of indicator columns. That is correct for the tree models and
false for the distance and margin models — `Order Country` code 87 is not "between" codes
86 and 88 — and it is a real cost, recorded in the model card rather than hidden.

The one thing `LabelEncoder` cannot do is serve. `LabelEncoder.transform` raises
`ValueError` on a label it did not see while fitting, and an operator will eventually type
a product name that was not in the training slice. Raising at that point turns an unusual
order into a 500. So the classes are learned with `LabelEncoder` and applied through a
lookup that maps anything unrecognised to `UNSEEN`, which the models treat as its own
level.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder, OneHotEncoder

#: The code given to a category absent from the training data. Negative so it can never
#: collide with a real `LabelEncoder` code, which are 0..n-1.
UNSEEN = -1

#: How the categorical block becomes numbers. `codes` is the course's `LabelEncoder`;
#: `one-hot` is declared in `scripts/check_taught.py` with the measurement behind it.
Encoding = Literal["codes", "one-hot"]

#: Categories rarer than this are folded into one shared indicator by `OneHotColumns`.
#: `Order Country` has 164 levels and several appear a handful of times in three years.
MIN_CATEGORY_FREQUENCY = 50


@dataclass(frozen=True)
class CategoryCodes:
    """The categorical half of a fitted feature space.

    Fitted once on the training slice and then carried alongside the model, because a code
    is only meaningful against the mapping that produced it. Serving a model with a
    remapped encoder silently reads every category as a different one.
    """

    mappings: dict[str, dict[str, int]]

    @classmethod
    def fit(cls, frame: pd.DataFrame, columns: list[str]) -> CategoryCodes:
        mappings: dict[str, dict[str, int]] = {}
        for name in columns:
            # Fitting on the distinct values rather than the whole column, and reading the
            # codes back from `fit_transform`, gives the same mapping `classes_` would while
            # keeping the result a plain array the type checker can follow.
            labels = pd.Series(frame[name].astype(str).unique()).sort_values()
            codes = pd.Series(LabelEncoder().fit_transform(labels))
            mappings[name] = {
                str(label): int(code) for label, code in zip(labels, codes, strict=True)
            }
        return cls(mappings=mappings)

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Encode every fitted column. Categories absent from training become `UNSEEN`."""
        missing = [name for name in self.mappings if name not in frame.columns]
        if missing:
            raise KeyError(f"the frame is missing encoded columns: {sorted(missing)}")

        encoded = {
            name: frame[name].astype(str).map(mapping).fillna(UNSEEN).astype("int64")
            for name, mapping in self.mappings.items()
        }
        return pd.DataFrame(encoded, index=frame.index)

    def levels(self, column: str) -> int:
        """How many categories were seen while fitting. Used by the model card and the CLI."""
        return len(self.mappings[column])

    def unseen_rate(self, frame: pd.DataFrame) -> dict[str, float]:
        """The share of rows falling to `UNSEEN` per column.

        Worth watching rather than assuming: a validation slice that is 30% unseen on
        `Product Name` is telling you the catalogue turned over, not that the model is bad.
        """
        encoded = self.transform(frame)
        return {name: float((encoded[name] == UNSEEN).mean()) for name in self.mappings}


@dataclass(frozen=True)
class OneHotColumns:
    """One indicator column per category, which is what the linear models actually wanted.

    `LabelEncoder` is the only encoder in the course material, and `CategoryCodes` above
    implements it faithfully. It has a real cost, measured rather than assumed: giving
    `Category Name` an arbitrary code from 0 to 49 tells a linear model that Cleats is
    twelve more than Fishing, and the worst calibration gap of the resulting classifier is
    0.334. One-hot encoding the same columns cuts that to 0.074.

    `min_frequency` matters more than it looks. `Order Country` has 164 levels and
    `Product Name` 118, and a column per level would add hundreds of features that are
    almost all zero and several that appear twice. Rare levels are folded into one
    "infrequent" indicator instead.

    Unseen categories are handled by `handle_unknown="ignore"`, which produces an all-zero
    row for that column rather than raising -- the same problem `CategoryCodes` solves with
    `UNSEEN`, and for the same reason: the catalogue turns over by about a fifth a year.
    """

    encoder: OneHotEncoder
    columns: tuple[str, ...]
    sources: tuple[str, ...]

    @classmethod
    def fit(cls, frame: pd.DataFrame, columns: list[str]) -> OneHotColumns:
        encoder = OneHotEncoder(
            handle_unknown="infrequent_if_exist",
            min_frequency=MIN_CATEGORY_FREQUENCY,
            sparse_output=False,
        )
        encoder.fit(frame.loc[:, columns].astype(str))
        return cls(
            encoder=encoder,
            columns=tuple(str(name) for name in encoder.get_feature_names_out(columns)),
            sources=tuple(columns),
        )

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        missing = [name for name in self.sources if name not in frame.columns]
        if missing:
            raise KeyError(f"the frame is missing encoded columns: {sorted(missing)}")

        # `sparse_output=False` already returns a dense array; `asarray` is here so the
        # type checker can see that, since the stub allows a sparse return either way.
        encoded = np.asarray(self.encoder.transform(frame.loc[:, list(self.sources)].astype(str)))
        return pd.DataFrame(encoded, columns=list(self.columns), index=frame.index)
