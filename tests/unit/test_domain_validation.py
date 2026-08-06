from __future__ import annotations

import unittest

from banbo.domain.errors import FailureCode
from banbo.domain.models import (
    Direction,
    DocumentSource,
    ParseEvidence,
    SiteSpec,
    ValidatedResult,
)
from banbo.domain.validation import validate_evidence


def site(direction: Direction = Direction.TOP) -> SiteSpec:
    return SiteSpec(
        site_id="sample-site",
        name="测试站",
        url="https://example.test/topic/1.html",
        direction=direction,
        strategy="history_block",
        anchors=("测试站", "绝杀半波"),
        parser_version=1,
    )


def evidence(
    *,
    issue: int = 210,
    value: str = "绿单",
    direction: Direction = Direction.TOP,
    anchor_passed: bool = True,
    record_id: str | None = "1",
    expected_record_id: str | None = "1",
    same_record: bool = True,
    boundary_issues: tuple[int, ...] = (210,),
    document_relation: str = "same_document",
) -> ParseEvidence:
    return ParseEvidence(
        site_id="sample-site",
        target_issue=issue,
        value=value,
        document_id="doc-1",
        document_source=DocumentSource.PAGE,
        document_order=0,
        snippet=f"{issue}期 绝杀半波 {value}",
        parser_name="history_block",
        parser_version=1,
        direction=direction,
        anchor_passed=anchor_passed,
        keyword_passed=True,
        same_record=same_record,
        record_id=record_id,
        expected_record_id=expected_record_id,
        boundary_issues=boundary_issues,
        document_relation=document_relation,
    )


class DomainValidationTest(unittest.TestCase):
    def test_only_validation_gate_can_create_success(self) -> None:
        outcome = validate_evidence(site(), 210, [evidence()])

        self.assertIsInstance(outcome, ValidatedResult)
        self.assertEqual("绿单", outcome.value)
        self.assertEqual("doc-1", outcome.evidence.document_id)

    def test_missing_target_period_fails_closed(self) -> None:
        outcome = validate_evidence(site(), 210, [evidence(issue=209)])

        self.assertEqual(FailureCode.TARGET_PERIOD_MISSING, outcome.code)

    def test_same_period_conflict_fails_closed(self) -> None:
        outcome = validate_evidence(
            site(),
            210,
            [evidence(value="绿单"), evidence(value="红单")],
        )

        self.assertEqual(FailureCode.SAME_PERIOD_CONFLICT, outcome.code)

    def test_wrong_direction_fails_closed(self) -> None:
        outcome = validate_evidence(
            site(Direction.BOTTOM),
            210,
            [evidence(direction=Direction.TOP)],
        )

        self.assertEqual(FailureCode.DIRECTION_MISMATCH, outcome.code)

    def test_missing_direction_window_fails(self) -> None:
        outcome = validate_evidence(
            site(),
            210,
            [evidence(boundary_issues=())],
        )

        self.assertEqual(FailureCode.DIRECTION_WINDOW_INVALID, outcome.code)

    def test_missing_anchor_fails_closed(self) -> None:
        outcome = validate_evidence(site(), 210, [evidence(anchor_passed=False)])

        self.assertEqual(FailureCode.ANCHOR_MISSING, outcome.code)

    def test_invalid_half_wave_fails_closed(self) -> None:
        outcome = validate_evidence(site(), 210, [evidence(value="绿波")])

        self.assertEqual(FailureCode.FIELD_INVALID, outcome.code)

    def test_record_id_mismatch_fails_closed(self) -> None:
        outcome = validate_evidence(
            site(),
            210,
            [evidence(record_id="2", expected_record_id="1")],
        )

        self.assertEqual(FailureCode.RECORD_ID_MISMATCH, outcome.code)

    def test_cross_record_join_fails_closed(self) -> None:
        outcome = validate_evidence(site(), 210, [evidence(same_record=False)])

        self.assertEqual(FailureCode.DOCUMENT_BOUNDARY_MISMATCH, outcome.code)

    def test_unregistered_document_relation_fails_closed(self) -> None:
        outcome = validate_evidence(
            site(),
            210,
            [evidence(document_relation="unknown")],
        )

        self.assertEqual(FailureCode.DOCUMENT_BOUNDARY_MISMATCH, outcome.code)

    def test_evidence_from_another_site_fails_closed(self) -> None:
        foreign = evidence()
        foreign = ParseEvidence(
            **{**foreign.__dict__, "site_id": "other-site"}
        )

        outcome = validate_evidence(site(), 210, [foreign])

        self.assertEqual(FailureCode.INTERNAL_ERROR, outcome.code)


if __name__ == "__main__":
    unittest.main()
