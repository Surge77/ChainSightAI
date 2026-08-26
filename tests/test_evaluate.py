"""Metrics computed by hand have to agree with the definitions they claim to implement."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chainsight import evaluate


def test_a_perfect_classifier_scores_one_everywhere() -> None:
    truth = pd.Series([0, 1, 1, 0, 1])

    scores = evaluate.classification_scores(truth, truth.to_numpy())

    assert scores == {"accuracy": 1.0, "precision": 1.0, "recall": 1.0, "f1": 1.0}


def test_precision_and_recall_match_the_definitions_in_the_revision_notes() -> None:
    """Precision is TP/(TP+FP); recall is TP/(TP+FN). Two positives called, one right."""
    truth = pd.Series([1, 1, 0, 0])
    predicted = np.array([1, 0, 1, 0])

    scores = evaluate.classification_scores(truth, predicted)

    assert scores["precision"] == pytest.approx(0.5)
    assert scores["recall"] == pytest.approx(0.5)
    assert scores["f1"] == pytest.approx(0.5)
    assert scores["accuracy"] == pytest.approx(0.5)


def test_a_model_that_never_predicts_late_scores_zero_rather_than_raising() -> None:
    """The degenerate case is a finding, not a stack trace. It is also the majority baseline."""
    truth = pd.Series([1, 1, 0])

    scores = evaluate.classification_scores(truth, np.zeros(3, dtype="int64"))

    assert scores["precision"] == 0.0
    assert scores["recall"] == 0.0
    assert scores["f1"] == 0.0


def test_always_predicting_late_buys_perfect_recall() -> None:
    """The reason F1 alone cannot choose a model on this dataset."""
    truth = pd.Series([1, 1, 0])

    scores = evaluate.classification_scores(truth, np.ones(3, dtype="int64"))

    assert scores["recall"] == 1.0
    assert scores["precision"] == pytest.approx(2 / 3)


def test_the_confusion_matrix_is_laid_out_the_way_the_notes_draw_it() -> None:
    truth = pd.Series([0, 0, 1, 1, 1])
    predicted = np.array([0, 1, 0, 1, 1])

    matrix = evaluate.confusion(truth, predicted)

    assert matrix.loc["actual not late", "predicted not late"] == 1
    assert matrix.loc["actual not late", "predicted late"] == 1
    assert matrix.loc["actual late", "predicted not late"] == 1
    assert matrix.loc["actual late", "predicted late"] == 2


def test_a_perfect_regression_scores_zero_error_and_r2_of_one() -> None:
    truth = pd.Series([0.1, -0.2, 0.35])

    scores = evaluate.regression_scores(truth, truth.to_numpy())

    assert scores["mae"] == pytest.approx(0.0)
    assert scores["rmse"] == pytest.approx(0.0)
    assert scores["r2"] == pytest.approx(1.0)


def test_rmse_punishes_one_large_miss_more_than_mae_does() -> None:
    truth = pd.Series([0.0, 0.0, 0.0, 0.0])
    predicted = np.array([0.0, 0.0, 0.0, 1.0])

    scores = evaluate.regression_scores(truth, predicted)

    assert scores["mae"] == pytest.approx(0.25)
    assert scores["rmse"] == pytest.approx(0.5)


def test_the_score_table_renders_one_row_per_model() -> None:
    table = evaluate.as_table(
        {"majority class": {"accuracy": 0.5511}, "shipping-mode rule": {"accuracy": 0.6956}}
    )

    assert "| model | accuracy |" in table
    assert "| majority class | 0.5511 |" in table
    assert "| shipping-mode rule | 0.6956 |" in table


def test_the_markdown_renderer_handles_integers_without_pulling_in_tabulate() -> None:
    frame = pd.DataFrame({"predicted late": [1302, 7313]}, index=["not late", "late"])

    table = evaluate.as_markdown(frame)

    assert "| not late | 1302 |" in table
