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

import pandas as pd
from sklearn.preprocessing import LabelEncoder

#: The code given to a category absent from the training data. Negative so it can never
#: collide with a real `LabelEncoder` code, which are 0..n-1.
UNSEEN = -1


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
