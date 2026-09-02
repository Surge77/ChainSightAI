"""The command line is the only interface until the web app lands, so it is tested as one.

These tests call `main` with an argument list and read what came out, rather than calling
the command functions directly. That is deliberate: half of what can break here is in the
parser — a subcommand wired to the wrong handler, a flag that never reaches the code that
reads it — and calling the functions directly would test everything except that.

Every command runs against the committed 500-row slice, which is why the suite needs no
downloaded dataset.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from chainsight import cli, ingest, persistence, registry, training
from chainsight.features import ORDER_FIELDS

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = REPO_ROOT / "data" / "sample_orders.csv"


@pytest.fixture
def artefacts(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


@pytest.fixture
def trained(artefacts: Path) -> registry.Version:
    """One artefact on disk and registered, without going through the CLI to put it there."""
    run = training.train(SAMPLE)
    name = training.artefact_name(run)
    persistence.save(run.artefact, name, directory=artefacts)
    return registry.Registry(path=artefacts / registry.REGISTRY_NAME).register(
        run.manifest, name, note="a fixture"
    )


@pytest.fixture
def order_file(tmp_path: Path) -> Path:
    """A real order taken from the sample, so the fields are exactly the ones serving needs."""
    frame = ingest.ingest(SAMPLE)
    row = frame.iloc[0]
    fields = {name: row[name] for name in ORDER_FIELDS}
    fields["order date (DateOrders)"] = str(fields["order date (DateOrders)"])

    path = tmp_path / "order.json"
    path.write_text(
        json.dumps({k: (v.item() if hasattr(v, "item") else v) for k, v in fields.items()}),
        encoding="utf-8",
    )
    return path


def sample_args(*rest: str) -> list[str]:
    return [*rest, "--data", str(SAMPLE)]


class TestDescribe:
    def test_it_reports_the_table_and_what_ingest_removed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(sample_args("describe")) == 0

        printed = capsys.readouterr().out
        assert "late rate" in printed
        assert "drop: personal data" in printed or "drop: leak" in printed

    def test_the_committed_slice_can_be_named_with_a_flag(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(REPO_ROOT)

        assert cli.main(["describe", "--sample"]) == 0
        assert "500 rows" in capsys.readouterr().out

    def test_a_missing_dataset_says_how_to_get_it(self, tmp_path: Path) -> None:
        """The 92 MB file is gitignored, so this is the first thing a new clone hits."""
        with pytest.raises(SystemExit, match="fetch_data"):
            cli.main(["describe", "--data", str(tmp_path / "absent.csv")])


class TestLeakage:
    def test_it_prints_both_numbers_rather_than_asserting_the_leak(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(sample_args("leakage")) == 0
        assert "leak" in capsys.readouterr().out.lower()


class TestCompare:
    def test_a_single_candidate_can_be_named(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(sample_args("compare", "--only", "decision tree")) == 0

        printed = capsys.readouterr().out
        assert "decision tree" in printed
        assert "baseline: shipping-mode rule" in printed
        assert "clears both baselines" in printed

    def test_the_margin_table_is_a_different_comparison(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(sample_args("compare", "--margin")) == 0

        printed = capsys.readouterr().out
        assert "baseline: mean margin" in printed
        assert "beats the mean baseline" in printed


class TestTrain:
    def test_training_saves_registers_and_does_not_promote(
        self, artefacts: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(sample_args("train", "--artefacts", str(artefacts))) == 0

        printed = capsys.readouterr().out
        assert "saved as version 1" in printed
        assert "promoted" not in printed
        assert registry.Registry(path=artefacts / registry.REGISTRY_NAME).current() is None

    def test_the_artefact_and_its_manifest_are_both_on_disk(self, artefacts: Path) -> None:
        cli.main(sample_args("train", "--artefacts", str(artefacts)))

        names = persistence.stored(artefacts)
        assert len(names) == 1
        assert (artefacts / f"{names[0]}.json").is_file()

    def test_promote_makes_it_live_in_one_command(
        self, artefacts: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(sample_args("train", "--artefacts", str(artefacts), "--promote")) == 0

        assert "now scores orders" in capsys.readouterr().out
        assert registry.Registry(path=artefacts / registry.REGISTRY_NAME).current() is not None

    def test_a_note_is_carried_into_the_registry(self, artefacts: Path) -> None:
        cli.main(sample_args("train", "--artefacts", str(artefacts), "--note", "nightly"))

        assert registry.Registry(path=artefacts / registry.REGISTRY_NAME).get(1).note == "nightly"

    def test_a_named_model_is_trained_instead_of_the_default(self, artefacts: Path) -> None:
        cli.main(sample_args("train", "--artefacts", str(artefacts), "--model", "decision tree"))

        entry = registry.Registry(path=artefacts / registry.REGISTRY_NAME).get(1)
        assert entry.model_name == "decision tree"

    def test_a_promotion_that_would_be_a_regression_exits_nonzero(
        self, artefacts: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The guard has to bite through the CLI too, not only when called from Python."""
        known = registry.Registry(path=artefacts / registry.REGISTRY_NAME)
        known.register(_manifest_scoring(0.99), "an-unbeatable-model")
        known.promote(1)

        code = cli.main(sample_args("train", "--artefacts", str(artefacts), "--promote"))

        assert code == 1
        assert "not switched on" in capsys.readouterr().err
        current = known.current()
        assert current is not None and current.version == 1

    def test_force_pushes_it_through_the_guard(self, artefacts: Path) -> None:
        known = registry.Registry(path=artefacts / registry.REGISTRY_NAME)
        known.register(_manifest_scoring(0.99), "an-unbeatable-model")
        known.promote(1)

        code = cli.main(sample_args("train", "--artefacts", str(artefacts), "--promote", "--force"))

        assert code == 0
        current = known.current()
        assert current is not None and current.version == 2


class TestRegistryCommand:
    def test_an_empty_registry_says_nothing_is_serving(
        self, artefacts: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["registry", "--artefacts", str(artefacts)]) == 0

        printed = capsys.readouterr().out
        assert "no models registered" in printed
        assert "scoring orders: none yet" in printed

    def test_it_lists_what_is_trained(
        self, artefacts: Path, trained: registry.Version, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["registry", "--artefacts", str(artefacts)]) == 0
        assert trained.model_name in capsys.readouterr().out

    def test_a_version_can_be_promoted_from_the_command_line(
        self, artefacts: Path, trained: registry.Version, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["registry", "--artefacts", str(artefacts), "--promote", "1"]) == 0

        assert "now scores orders" in capsys.readouterr().out

    def test_a_refused_promotion_exits_nonzero_and_prints_the_reason(
        self, artefacts: Path, trained: registry.Version, capsys: pytest.CaptureFixture[str]
    ) -> None:
        known = registry.Registry(path=artefacts / registry.REGISTRY_NAME)
        known.register(_manifest_scoring(0.01), "a-terrible-model")
        known.promote(1)

        code = cli.main(["registry", "--artefacts", str(artefacts), "--promote", "2"])

        assert code == 1
        assert "Being newer does not make it better" in capsys.readouterr().err

    def test_the_metric_compared_on_can_be_named(
        self, artefacts: Path, trained: registry.Version
    ) -> None:
        known = registry.Registry(path=artefacts / registry.REGISTRY_NAME)
        known.register(_manifest_scoring(0.01, f1=0.99), "strong on f1 only")
        known.promote(1)

        code = cli.main(
            ["registry", "--artefacts", str(artefacts), "--promote", "2", "--metric", "f1"]
        )

        assert code == 0


class TestPredict:
    def test_a_template_names_every_field_an_order_needs(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cli.main(["predict", "--template"]) == 0

        assert set(json.loads(capsys.readouterr().out)) == set(ORDER_FIELDS)

    def test_an_order_produces_a_priority_and_the_arithmetic_behind_it(
        self,
        artefacts: Path,
        trained: registry.Version,
        order_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        registry.Registry(path=artefacts / registry.REGISTRY_NAME).promote(1)

        assert cli.main(["predict", str(order_file), "--artefacts", str(artefacts)]) == 0

        printed = capsys.readouterr().out
        assert "chance of being late" in printed
        assert "net saving if we act" in printed
        assert trained.model_name in printed

    def test_it_refuses_to_serve_when_nothing_has_been_promoted(
        self, artefacts: Path, trained: registry.Version, order_file: Path
    ) -> None:
        """A trained model is a candidate. Serving the newest thing in the list is the bug."""
        with pytest.raises(SystemExit, match="No model is switched on"):
            cli.main(["predict", str(order_file), "--artefacts", str(artefacts)])

    def test_an_order_file_is_required_unless_a_template_was_asked_for(self) -> None:
        with pytest.raises(SystemExit, match="--template"):
            cli.main(["predict"])

    def test_an_artefact_that_cannot_be_trusted_exits_nonzero(
        self, artefacts: Path, order_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        known = registry.Registry(path=artefacts / registry.REGISTRY_NAME)
        known.register(_manifest_scoring(0.75), "a-model-nobody-saved")
        known.promote(1)

        code = cli.main(["predict", str(order_file), "--artefacts", str(artefacts)])

        assert code == 1
        assert "no artefact called" in capsys.readouterr().err


def test_python_dash_m_reaches_the_same_entry_point() -> None:
    """Somebody with a fresh clone and no `pip install -e .` still has a way in."""
    module = importlib.import_module("chainsight.__main__")

    assert module.main is cli.main


def test_the_parser_refuses_a_command_it_does_not_have() -> None:
    with pytest.raises(SystemExit):
        cli.main(["deploy-to-production"])


def _manifest_scoring(roc: float, *, f1: float = 0.5) -> persistence.Manifest:
    return persistence.Manifest(
        model_name="a placeholder",
        encoding="one-hot",
        feature_hash="a" * 64,
        dataset_hash="b" * 64,
        rows_trained=1,
        threshold=0.2966,
        scores={"roc auc": roc, "f1": f1},
    )
