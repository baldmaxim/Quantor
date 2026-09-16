"""Неизменяемое происхождение контрактов MEP v0.3: калибровка, профиль, модели, корпус, проверка."""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.contracts.mep import (
    calibration_fingerprint,
    validate_evidence_graph,
    validate_network_graph,
)
from app.contracts.mep.common import CalibrationSnapshot
from tests.mep_fixtures import (
    EVIDENCE,
    NETWORK,
    PROFILE,
    Json,
    by_id,
    element,
    errors,
    evidence_model,
    network_model,
    profile_model,
)

REVIEWER = "user-reviewer-1"


class TestCalibrationSnapshot:
    def test_calibrated_sheet_carries_a_snapshot(self) -> None:
        data = copy.deepcopy(NETWORK)
        data["sheets"][0].pop("calibration")

        assert "CALIBRATION_SNAPSHOT_MISSING" in errors(validate_network_graph(network_model(data)))

    def test_changed_factor_breaks_the_fingerprint(self) -> None:
        data = copy.deepcopy(NETWORK)
        data["sheets"][0]["calibration"]["mm_per_pt"] = "35.3"

        found = errors(validate_network_graph(network_model(data)))

        assert "CALIBRATION_FINGERPRINT_MISMATCH" in found

    def test_snapshot_belongs_to_the_page(self) -> None:
        data = copy.deepcopy(EVIDENCE)
        data["sheets"][0]["geometry_fingerprint"] = "9" * 64

        found = errors(validate_evidence_graph(evidence_model(data)))

        assert "CALIBRATION_GEOMETRY_MISMATCH" in found

    def test_trailing_zeros_do_not_change_the_fingerprint(self) -> None:
        snapshot = dict(NETWORK["sheets"][0]["calibration"])
        padded = snapshot | {"mm_per_pt": "35.2777777777780", "display_width_pt": "2383.937"}

        assert calibration_fingerprint(
            CalibrationSnapshot.model_validate(padded)
        ) == calibration_fingerprint(CalibrationSnapshot.model_validate(snapshot))

    def test_factor_must_be_positive(self) -> None:
        snapshot = dict(NETWORK["sheets"][0]["calibration"]) | {"mm_per_pt": "0"}

        with pytest.raises(ValidationError):
            CalibrationSnapshot.model_validate(snapshot)


class TestProfileFingerprint:
    def test_graph_pins_profile_content(self) -> None:
        data = copy.deepcopy(NETWORK)
        data["profile"].pop("profile_sha256")

        found = errors(validate_network_graph(network_model(data), profile=profile_model()))

        assert "PROFILE_NOT_PINNED" in found

    def test_edited_profile_without_new_version_is_detected(self) -> None:
        edited = copy.deepcopy(PROFILE)
        edited["systems"][0]["topology"] = "any"

        found = errors(validate_evidence_graph(evidence_model(), profile_model(edited)))

        assert "PROFILE_FINGERPRINT_MISMATCH" in found


class TestGenerationProvenance:
    def test_model_tool_carries_weights_and_config(self) -> None:
        data = copy.deepcopy(NETWORK)
        data["tools"][0]["model_id"] = "synthetic-gnn"

        found = errors(validate_network_graph(network_model(data)))

        assert "MODEL_PROVENANCE_INCOMPLETE" in found

    def test_steps_need_a_run(self) -> None:
        data = copy.deepcopy(NETWORK)
        data.pop("run")

        assert "RUN_PROVENANCE_MISSING" in errors(validate_network_graph(network_model(data)))

    def test_step_belongs_to_the_run(self) -> None:
        data = copy.deepcopy(NETWORK)
        by_id(data["inference_steps"], "st-4")["run_id"] = "run-other"

        assert "STEP_RUN_MISMATCH" in errors(validate_network_graph(network_model(data)))

    def test_retrieved_cases_name_their_corpus(self) -> None:
        data = copy.deepcopy(NETWORK)
        by_id(data["inference_steps"], "st-2").pop("corpus_id")

        assert "CORPUS_NOT_PINNED" in errors(validate_network_graph(network_model(data)))

    def test_unknown_corpus(self) -> None:
        data = copy.deepcopy(NETWORK)
        by_id(data["inference_steps"], "st-2")["corpus_id"] = "corpus-missing"

        assert "UNKNOWN_CORPUS" in errors(validate_network_graph(network_model(data)))

    def test_heldout_split_cannot_be_a_retrieval_corpus(self) -> None:
        data = copy.deepcopy(NETWORK)
        data["corpora"][0]["split"] = "test"

        with pytest.raises(ValidationError):
            network_model(data)


def _event(event_id: str, action: str, at: str) -> Json:
    return {"event_id": event_id, "action": action, "reviewer_id": REVIEWER, "reviewed_at": at}


def _hybrid() -> Json:
    """ev-term-2 сдвинут человеком, ev-term-1 подтверждён, остальное — как предсказала модель."""
    data = copy.deepcopy(EVIDENCE)
    data["input_mode"] = "HYBRID_REVIEWED"
    moved = element(data, "ev-term-2")
    moved["original"] = {
        "provenance": "mep_model_observed",
        "tool_id": "det",
        "class_key": moved["class_key"],
        "geometry": {"kind": "point", "point": [0.61, 0.71]},
        "confidence": moved["confidence"],
        "sources": moved["sources"],
    }
    moved.update(provenance="human_ground_truth", status="human_confirmed", review="confirmed")
    moved["sources"] = [{"source_type": "human_annotation", "ref_id": "ann-7"}, *moved["sources"]]
    moved["review_history"] = [_event("rv-2", "correct_geometry", "2026-09-15T10:05:00Z")]
    confirmed = element(data, "ev-term-1")
    confirmed.update(status="human_confirmed", review="confirmed")
    confirmed["review_history"] = [_event("rv-1", "confirm", "2026-09-15T10:00:00Z")]
    return data


class TestHybridReview:
    def test_reviewed_graph_is_valid(self) -> None:
        assert errors(validate_evidence_graph(evidence_model(_hybrid()), profile_model())) == set()

    def test_correction_keeps_the_original_prediction(self) -> None:
        data = _hybrid()
        element(data, "ev-term-2").pop("original")

        found = errors(validate_evidence_graph(evidence_model(data)))

        assert "ORIGINAL_PREDICTION_MISSING" in found

    def test_every_change_is_recorded(self) -> None:
        data = _hybrid()
        element(data, "ev-term-2")["review_history"] = [
            _event("rv-2", "confirm", "2026-09-15T10:05:00Z")
        ]

        assert "UNRECORDED_CORRECTION" in errors(validate_evidence_graph(evidence_model(data)))

    def test_confirmation_has_history(self) -> None:
        data = _hybrid()
        element(data, "ev-term-1")["review_history"] = []

        assert "REVIEW_HISTORY_MISSING" in errors(validate_evidence_graph(evidence_model(data)))

    def test_history_is_chronological(self) -> None:
        data = _hybrid()
        element(data, "ev-term-2")["review_history"] = [
            _event("rv-3", "mark_ambiguous", "2026-09-15T11:00:00Z"),
            _event("rv-2", "correct_geometry", "2026-09-15T10:05:00Z"),
        ]

        assert "REVIEW_HISTORY_ORDER" in errors(validate_evidence_graph(evidence_model(data)))

    def test_corrected_element_is_no_longer_model_output(self) -> None:
        data = _hybrid()
        moved = element(data, "ev-term-2")
        moved.update(provenance="mep_model_observed", status="observed", review="unreviewed")
        moved["sources"] = moved["sources"][1:]

        found = errors(validate_evidence_graph(evidence_model(data)))

        assert "CORRECTION_NOT_REFLECTED" in found

    def test_added_element_has_no_original(self) -> None:
        data = _hybrid()
        added = copy.deepcopy(element(data, "ev-term-1"))
        added.update(id="ev-added-1", provenance="human_ground_truth")
        added["geometry"] = {"kind": "point", "point": [0.7, 0.2]}
        added["sources"] = [{"source_type": "human_annotation", "ref_id": "ann-8"}]
        added["review_history"] = [_event("rv-4", "add_missing", "2026-09-15T10:10:00Z")]
        data["elements"].append(added)

        assert errors(validate_evidence_graph(evidence_model(data))) == set()

    def test_timestamp_needs_a_timezone(self) -> None:
        data = _hybrid()
        element(data, "ev-term-1")["review_history"][0]["reviewed_at"] = "2026-09-15T10:00:00"

        with pytest.raises(ValidationError):
            evidence_model(data)

    def test_model_extracted_graph_has_no_review(self) -> None:
        data = _hybrid()
        data["input_mode"] = "MODEL_EXTRACTED"

        assert "INPUT_MODE_CONFLICT" in errors(validate_evidence_graph(evidence_model(data)))
