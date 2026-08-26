"""Split by time, because the question is about the future.

The course splits with `train_test_split`, and its reason for doing so is the right one:
test on data the model has not seen, or the score is not honest. A shuffled split on this
table satisfies the letter of that and not the point. Orders from March 2017 would train a
model scored on orders from January 2017, and the model would be asked to predict a past
it had already been shown.

So the split is chronological. Train on the oldest slice, tune on the next, and touch the
newest once. `at_random` is kept alongside it, using the course's own
`train_test_split`, so `leakage.py` can put the two side by side and show what the
shuffle is worth — which on this dataset turns out to be very little, because the target
is remarkably stable across years. That result is worth having precisely because it is
not the one people expect.

The default boundaries put 2015 and 2016 in training, the first half of 2017 in
validation, and everything from July 2017 onward in test.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.model_selection import train_test_split

from chainsight import schema

#: Orders before this date train the model.
VALIDATION_START = pd.Timestamp("2017-01-01")

#: Orders from this date onward are the held-out test slice, looked at once.
TEST_START = pd.Timestamp("2017-07-01")

#: The course's own seed, so a shuffled split here is reproducible the way the notebooks are.
RANDOM_STATE = 42


@dataclass(frozen=True)
class Split:
    """Three disjoint slices of one frame, and how they were cut."""

    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    how: str

    def __post_init__(self) -> None:
        if min(len(self.train), len(self.validation), len(self.test)) == 0:
            raise ValueError(
                f"a {self.how} split left an empty slice: "
                f"{len(self.train)}/{len(self.validation)}/{len(self.test)}"
            )

    @property
    def sizes(self) -> dict[str, int]:
        return {
            "train": len(self.train),
            "validation": len(self.validation),
            "test": len(self.test),
        }

    def summary(self) -> str:
        lines = [f"{self.how} split"]
        for name, part in (
            ("train", self.train),
            ("validation", self.validation),
            ("test", self.test),
        ):
            dates = part[schema.ORDER_DATE]
            late = part[schema.LATE_TARGET].mean()
            lines.append(
                f"  {name:<10} {len(part):>7,} rows  "
                f"{dates.min():%Y-%m-%d} to {dates.max():%Y-%m-%d}  late {late:.4f}"
            )
        return "\n".join(lines)


def by_date(
    frame: pd.DataFrame,
    *,
    validation_start: pd.Timestamp = VALIDATION_START,
    test_start: pd.Timestamp = TEST_START,
) -> Split:
    """Train on the past, tune on the middle, and keep the newest slice for one look."""
    if validation_start >= test_start:
        raise ValueError(
            f"validation must start before test: {validation_start:%Y-%m-%d} "
            f"is not before {test_start:%Y-%m-%d}"
        )

    ordered = frame[schema.ORDER_DATE]
    return Split(
        train=frame.loc[ordered < validation_start].reset_index(drop=True),
        validation=frame.loc[(ordered >= validation_start) & (ordered < test_start)].reset_index(
            drop=True
        ),
        test=frame.loc[ordered >= test_start].reset_index(drop=True),
        how="chronological",
    )


def at_random(frame: pd.DataFrame, *, test_size: float = 0.2) -> Split:
    """A shuffled split, for comparison only. Never used to report a headline number.

    This exists so the difference between the two can be measured rather than asserted.
    Using it to train a model that is then described as predicting late deliveries would
    be the exact error `by_date` is here to avoid.
    """
    rest, test = _shuffle(frame, test_size)
    train, validation = _shuffle(rest, test_size)
    return Split(train=train, validation=validation, test=test, how="shuffled")


def _shuffle(frame: pd.DataFrame, test_size: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`train_test_split` is typed as returning a list, so name the two halves here."""
    left, right = train_test_split(frame, test_size=test_size, random_state=RANDOM_STATE)
    return (
        pd.DataFrame(left).reset_index(drop=True),
        pd.DataFrame(right).reset_index(drop=True),
    )
