"""Scores, in the metrics the curriculum covers.

`roc_auc_score` appears nowhere in the notebooks or the revision notes, so it appears
nowhere here. What the material does cover is accuracy, the confusion matrix, and
precision, recall and F1 out of `classification_report` — which is enough, and arguably
better, because it forces an operating threshold to be named rather than integrated over.

The revision notes make the case against accuracy with the 99%-not-spam example. This
dataset makes it more sharply: adding payment type to the one-rule model moves accuracy by
nothing at all while moving predicted probability on 7,813 orders from 1.00 to 0.83. So
accuracy is reported, and it is never reported alone.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)

#: Predicted probability at or above this counts as late, until the decision engine derives
#: a threshold from the cost of intervening. 0.5 is a placeholder, not a recommendation.
DEFAULT_THRESHOLD = 0.5


def classification_scores(Y_true: pd.Series, Y_pred: np.ndarray | pd.Series) -> dict[str, float]:
    """Accuracy, precision, recall and F1 for the late class.

    Precision, recall and F1 are computed from the confusion matrix rather than imported.
    They are three lines of the arithmetic the revision notes spell out -- precision is
    TP/(TP+FP), recall is TP/(TP+FN) -- and doing it here means a model that predicts no
    positives at all scores zero rather than raising or warning. A degenerate model should
    produce a bad number: the number is the finding.
    """
    _not_late_correct, false_positive, false_negative, true_positive = confusion_matrix(
        Y_true, Y_pred, labels=[0, 1]
    ).ravel()

    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    return {
        "accuracy": float(accuracy_score(Y_true, Y_pred)),
        "precision": precision,
        "recall": recall,
        "f1": _ratio(2 * precision * recall, precision + recall),
    }


def _ratio(numerator: float, denominator: float) -> float:
    """Zero when there is nothing to divide, which is the honest answer for these three."""
    return float(numerator / denominator) if denominator else 0.0


def confusion(Y_true: pd.Series, Y_pred: np.ndarray | pd.Series) -> pd.DataFrame:
    """The confusion matrix, labelled, in the layout the revision notes use."""
    matrix = confusion_matrix(Y_true, Y_pred, labels=[0, 1])
    return pd.DataFrame(
        matrix,
        index=pd.Index(["actual not late", "actual late"]),
        columns=pd.Index(["predicted not late", "predicted late"]),
    )


def regression_scores(Y_true: pd.Series, Y_pred: np.ndarray | pd.Series) -> dict[str, float]:
    """MAE, RMSE and R-squared.

    MAE leads because it is the one that can be said out loud: the margin prediction is off
    by this much, on average, in the units of the thing being predicted.
    """
    mse = float(mean_squared_error(Y_true, Y_pred))
    return {
        "mae": float(mean_absolute_error(Y_true, Y_pred)),
        "rmse": float(np.sqrt(mse)),
        "r2": float(r2_score(Y_true, Y_pred)),
    }


def ranking_scores(Y_true: pd.Series, probabilities: np.ndarray) -> dict[str, float]:
    """How well the model *orders* orders, which is what a control tower actually needs.

    Accuracy and F1 both answer a question nobody here asks -- "is this order late, yes or
    no" -- and on this dataset they answered it so similarly for every model that they hid
    the difference between them. Ranking is the product: the operator works down a list.

    Both numbers are threshold-free, and they disagree usefully. ROC-AUC weights the two
    classes equally; average precision follows the positive class, which is the one that
    costs money when missed.
    """
    return {
        "roc auc": float(roc_auc_score(Y_true, probabilities)),
        "avg precision": float(average_precision_score(Y_true, probabilities)),
    }


def threshold_sweep(
    Y_true: pd.Series,
    probabilities: np.ndarray,
    *,
    steps: tuple[float, ...] = (0.2, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.7, 0.8),
) -> pd.DataFrame:
    """Precision, recall, F1 and accuracy at each threshold, and how many orders it flags.

    This is what stands in for a ROC curve, which is not in the curriculum. It is arguably
    the more useful object anyway: a curve integrates over every threshold including the
    ones nobody would ship, while this table names the operating points and says what each
    one costs in orders flagged. The decision engine picks a row from it.
    """
    rows = []
    for threshold in steps:
        predicted = (probabilities >= threshold).astype("int64")
        scores = classification_scores(Y_true, predicted)
        rows.append({"threshold": threshold, **scores, "flagged": int(predicted.sum())})
    return pd.DataFrame(rows).set_index("threshold")


def reliability(Y_true: pd.Series, probabilities: np.ndarray, *, bins: int = 10) -> pd.DataFrame:
    """Predicted probability against observed rate, in deciles of predicted probability.

    A model claiming 0.80 should be late about 80% of the time on the orders it says that
    about. Nothing here corrects a badly calibrated model -- `CalibratedClassifierCV` is
    outside the curriculum -- but the decision engine multiplies this probability by money,
    so a model that is confidently wrong needs to be visible before it is deployed.
    """
    frame = pd.DataFrame({"predicted": probabilities, "actual": Y_true.to_numpy()})
    edges = [index / bins for index in range(bins + 1)]
    frame["bin"] = pd.cut(frame["predicted"], bins=edges, include_lowest=True)

    grouped = frame.groupby("bin", observed=True).agg(
        orders=("actual", "size"),
        mean_predicted=("predicted", "mean"),
        observed_rate=("actual", "mean"),
    )
    grouped["gap"] = grouped["mean_predicted"] - grouped["observed_rate"]
    return grouped.round(4)


def as_table(scores: dict[str, dict[str, float]], *, decimals: int = 4) -> str:
    """A markdown table of named score dicts, for `docs/results.md` and the CLI."""
    return as_markdown(pd.DataFrame(scores).T, corner="model", decimals=decimals)


def as_markdown(frame: pd.DataFrame, *, corner: str = "", decimals: int | None = None) -> str:
    """Render a frame as a markdown table.

    `DataFrame.to_markdown` would do this, and pulls in `tabulate` to do it. A table with a
    header row and a rule is not worth a dependency.
    """

    def cell(value: object) -> str:
        # A model without `predict_proba` has no ranking score, and an empty cell says that
        # better than `nan` does. `SVC` is the case that put this here.
        if isinstance(value, float) and np.isnan(value):
            return "-"
        return f"{value:.{decimals}f}" if decimals is not None else str(value)

    header = f"| {corner} | " + " | ".join(str(name) for name in frame.columns) + " |"
    rule = "|---" * (len(frame.columns) + 1) + "|"
    rows = [
        f"| {index} | " + " | ".join(cell(value) for value in row) + " |"
        for index, row in frame.iterrows()
    ]
    return "\n".join([header, rule, *rows])
