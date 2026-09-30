import json
from copy import deepcopy
from pathlib import Path

from banbo.domain import Direction, DocumentSource, ParseEvidence, ValidatedResult
from banbo.storage import RecentCacheRepository


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_qiangdatianxia_uses_verified_http_and_exact_topic_boundary():
    payload = json.loads(
        (PROJECT_ROOT / "config" / "parser_specs.json").read_text(
            encoding="utf-8"
        )
    )
    spec = next(
        item for item in payload["specs"] if item["site_id"] == "hw-0030"
    )

    assert spec["options"]["verify_ssl"] is False
    assert spec["topic_id_pattern"] == r"/topic/(?P<topic_id>\d+)\.html"
    assert spec["parser_id"] == "hw-0030:nearest_document:v2"
    assert spec["parser_version"] == "2"


def test_targeted_new_period_changes_only_requested_site_row(tmp_path):
    issues = list(range(244, 234, -1))
    payload = {
        "schema": 1,
        "window_size": 10,
        "issues": issues,
        "sites": [
            {
                "name": "枪打天下",
                "url": "https://example.test/topic/448452.html",
                "pick": "top",
                "second_click": False,
                "values": {"244": "绿单"},
                "failures": {},
            },
            {
                "name": "其他站点",
                "url": "https://other.test/topic/1.html",
                "pick": "bottom",
                "second_click": False,
                "values": {"244": "红单", "235": "蓝双"},
                "failures": {},
            },
        ],
        "parser_versions": {"hw-0030": "1", "hw-other": "1"},
    }
    other_before = deepcopy(payload["sites"][1])
    evidence = ParseEvidence(
        site_id="hw-0030",
        target_issue=246,
        value="蓝双",
        document_id="doc",
        document_source=DocumentSource.SCRIPT,
        document_order=1,
        snippet="246期绝杀半波蓝双",
        parser_name="nearest_document",
        parser_version="2",
        direction=Direction.TOP,
        anchor_passed=True,
        keyword_passed=True,
        same_record=True,
    )
    result = ValidatedResult(
        site_id="hw-0030",
        site_name="枪打天下",
        target_issue=246,
        value="蓝双",
        direction=Direction.TOP,
        evidence=evidence,
        parser_version="2",
    )

    updated = RecentCacheRepository(tmp_path / "cache.json").prepare_targeted_period(
        [result],
        site_names_by_id={"hw-0030": "枪打天下"},
        target_issue=246,
        site_rows_by_id={
            "hw-0030": {
                "name": "枪打天下",
                "url": "https://example.test/topic/448452.html",
                "pick": "top",
                "second_click": False,
            }
        },
        base_payload=payload,
        run_id="repair-246",
    )

    assert updated["issues"] == issues
    assert updated["partial_issues"] == [246]
    assert updated["sites"][0]["values"]["246"] == "蓝双"
    assert updated["sites"][1] == other_before
    assert updated["parser_versions"]["hw-0030"] == "2"
    RecentCacheRepository.validate(updated)
