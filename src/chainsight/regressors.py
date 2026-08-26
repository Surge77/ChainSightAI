"""The margin regressors, which is a short list on purpose.

The notebooks cover `LinearRegression`, `Ridge`, `Lasso` and `PolynomialFeatures`. They
cover no tree or ensemble regressor at all — `RandomForestRegressor` and friends appear
nowhere in the material — so the margin model is linear, and that is a real constraint
rather than a preference.

It matters here more than it would elsewhere, because `LabelEncoder` gives `Category Name`
an arbitrary integer code from 0 to 49. A tree is indifferent to that ordering; a linear
model reads it as a quantity, so "Cleats is 12 more than Fishing" is arithmetic the model
is obliged to take seriously. The categorical block is therefore effectively unavailable to
everything in this file.

Whether that costs anything is not assumed. `ceiling.py` measures what the categorical
columns are worth to a predictor that cheats, and `docs/results.md` reports the answer.

`Lasso` is included for a specific reason beyond completeness. The revision notes describe
L1 as feature selection that can push coefficients to exactly zero, and the 23-column
feature space contains eight derived columns measured to be near-worthless for the delivery
target. Watching which ones survive is the demonstration of that line.
"""

from __future__ import annotations

from sklearn.linear_model import Lasso, LinearRegression, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

from chainsight.models import Candidate

#: Degree 2 over 23 features is 300 columns. Degree 3 is 2,600, and takes minutes to fit
#: for a model already measured to have nothing to find.
POLYNOMIAL_DEGREE = 2


def _scaled(model: object) -> Pipeline:
    return Pipeline([("Scaler", StandardScaler()), ("Model", model)])


REGRESSORS: tuple[Candidate, ...] = (
    Candidate(
        name="linear regression",
        build=lambda: _scaled(LinearRegression()),
    ),
    Candidate(
        name="ridge",
        build=lambda: _scaled(Ridge()),
        grid={"Model__alpha": [0.1, 1.0, 10.0, 100.0]},
    ),
    Candidate(
        name="lasso",
        build=lambda: _scaled(Lasso(max_iter=10000)),
        grid={"Model__alpha": [0.001, 0.01, 0.1]},
        note="L1, so its surviving coefficients are the feature selection the notes describe",
    ),
    Candidate(
        name="polynomial linear",
        build=lambda: Pipeline(
            [
                # Poly first, then scale. The cheatsheet is explicit about the order.
                ("Poly", PolynomialFeatures(degree=POLYNOMIAL_DEGREE, include_bias=False)),
                ("Scaler", StandardScaler()),
                ("Model", LinearRegression()),
            ]
        ),
        note=f"degree {POLYNOMIAL_DEGREE}, which turns 23 features into roughly 300",
    ),
)


def by_name(name: str) -> Candidate:
    for candidate in REGRESSORS:
        if candidate.name == name:
            return candidate
    available = ", ".join(candidate.name for candidate in REGRESSORS)
    raise KeyError(f"no regressor called {name!r}. Available: {available}")


def names() -> list[str]:
    return [candidate.name for candidate in REGRESSORS]
