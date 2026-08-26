"""One feature builder, used by training and by serving.

Two implementations of this would be two implementations, and they would disagree within a
month — the training one gaining a column, the serving one not, and the model quietly
reading the wrong number in the wrong slot. So there is one, `FeatureSpace`, fitted on the
training slice and carried with the model.

The derived features here are mostly measured to be worthless, and that is deliberate. On
the full table the late-delivery rate varies by 0.0010 across the weekend flag, 0.0087
across day of week and 0.0078 across quantity, against 0.5725 across `Shipping Mode`. They
are built anyway so that `Lasso` can drive their coefficients to zero and the results
document can show it happening, rather than this file asserting it. The cheatsheet's line
about L1 being feature selection deserves a demonstration.

The margin target is the other way round: `Category Name` spans 0.1385 and
`Department Name` 0.0522, so the categorical block is where that model's signal lives.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from chainsight import schema
from chainsight.encoding import CategoryCodes, Encoding, OneHotColumns

#: Categorical columns, encoded to integer codes. Every one is known at order time.
CATEGORICAL: tuple[str, ...] = (
    "Type",
    "Category Name",
    "Customer Country",
    "Customer Segment",
    "Customer State",
    "Department Name",
    "Market",
    "Order Country",
    "Order Region",
    "Product Name",
    "Shipping Mode",
)

#: Numeric columns passed through as they arrive.
NUMERIC: tuple[str, ...] = (
    "Order Item Discount Rate",
    "Order Item Quantity",
    "Order Item Total",
    "Product Price",
)

#: The country the destination column uses for the United States. `Customer Country` spells
#: the same country "EE. UU.", so comparing the two as strings would make every order look
#: international. Two vocabularies for one place, in one table.
_DOMESTIC_DESTINATION = "Estados Unidos"

_WEEKEND_STARTS = 5


def derive(frame: pd.DataFrame) -> pd.DataFrame:
    """The engineered columns, before encoding. Every one computable from a single order."""
    ordered = frame[schema.ORDER_DATE]
    quantity = frame["Order Item Quantity"]
    return pd.DataFrame(
        {
            "order_month": ordered.dt.month,
            "order_quarter": ordered.dt.quarter,
            "order_day_of_week": ordered.dt.dayofweek,
            "order_day_of_month": ordered.dt.day,
            "order_is_weekend": (ordered.dt.dayofweek >= _WEEKEND_STARTS).astype("int64"),
            "gross_value": frame["Product Price"] * quantity,
            "value_per_unit": frame["Order Item Total"] / quantity,
            "is_domestic_destination": (frame["Order Country"] == _DOMESTIC_DESTINATION).astype(
                "int64"
            ),
        },
        index=frame.index,
    )


@dataclass(frozen=True)
class FeatureSpace:
    """A fitted feature builder: the category encoder, and the column order.

    The column order is stored rather than recomputed. scikit-learn estimators index
    features positionally once fitted, so a frame with the right columns in the wrong
    order predicts confidently and wrongly, with nothing to see in a traceback.
    """

    codes: CategoryCodes | OneHotColumns
    columns: tuple[str, ...]
    encoding: Encoding = "codes"

    @classmethod
    def fit(cls, frame: pd.DataFrame, *, encoding: Encoding = "codes") -> FeatureSpace:
        """Learn the encoding from this frame, which must be the training slice only.

        `codes` keeps the project inside the course material and gives every category an
        arbitrary integer that linear models read as a quantity. `one-hot` costs a wider
        matrix and buys a calibration gap of 0.074 in place of 0.334.
        """
        codes: CategoryCodes | OneHotColumns = (
            CategoryCodes.fit(frame, list(CATEGORICAL))
            if encoding == "codes"
            else OneHotColumns.fit(frame, list(CATEGORICAL))
        )
        # The column list is read off a real transform rather than assembled by hand, so the
        # two can never disagree about what the encoder produced.
        built = _assemble(codes, frame)
        return cls(codes=codes, columns=tuple(built.columns), encoding=encoding)

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        """The numeric feature matrix, in the fitted column order."""
        return _assemble(self.codes, frame).loc[:, list(self.columns)]

    def fit_transform(self, _frame: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError(
            "fit on the training slice and transform the others separately. A combined call "
            "is the shape of the mistake this class exists to prevent."
        )


def _assemble(codes: CategoryCodes | OneHotColumns, frame: pd.DataFrame) -> pd.DataFrame:
    """Encoded categoricals, numeric passthroughs and derived columns, in that order."""
    return pd.concat([codes.transform(frame), frame.loc[:, list(NUMERIC)], derive(frame)], axis=1)


#: The at-order fields an operator supplies. The serving path builds a frame from these and
#: hands it to the same `FeatureSpace.transform` that training used.
ORDER_FIELDS: tuple[str, ...] = tuple(CATEGORICAL) + tuple(NUMERIC) + (schema.ORDER_DATE,)


def single_order(**fields: object) -> pd.DataFrame:
    """A one-row frame from an operator's inputs, shaped exactly like an ingested frame.

    Serving does not get to take a shortcut. If this produced anything other than the
    columns `transform` expects, the difference would show up as a wrong prediction rather
    than as an error, so the field list is checked here.
    """
    missing = sorted(set(ORDER_FIELDS) - set(fields))
    if missing:
        raise KeyError(f"an order needs {missing}")
    unknown = sorted(set(fields) - set(ORDER_FIELDS))
    if unknown:
        raise KeyError(f"an order has no {unknown}")

    row = pd.DataFrame([fields], columns=list(ORDER_FIELDS))
    row[schema.ORDER_DATE] = pd.to_datetime(row[schema.ORDER_DATE])
    return row
