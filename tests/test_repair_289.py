"""修复 1：正式成功/失败 TXT 不得被整份覆盖。

299 期事故：只跑 3 个站，正式模式把 195 站的 `299期-半波.txt` 写成 3 行。
根因是 `cli.py` 里 `operations[success_path] = render_success_report(period, runs)`
无条件重写，失败 TXT 同理被清空。

修复后语义（单期入口与多期入口共用 `_plan_period_reports`）：
- 覆盖到且成功：TXT 无行→追加；TXT 同值→不动；TXT 不同值→冲突，不覆盖、改记
  失败，除非显式 `--accept-verified`（解析器已修复并重新验证）。
- 覆盖到且失败：本期已有定稿值→保留值，失败目录写「保留」记录（可见、不重抓）；
  没有定稿值→普通「失败」记录。
- 未覆盖的站点：行与失败记录原样保留；配置外的行一并保留并计入排行。
- 缓存基准是第二个冲突源；TXT 与本次结果一致而缓存不同时，缓存按 TXT 对齐。
"""

from __future__ import annotations

import json
from typing import ClassVar

from banbo import cli, multi_cli
from banbo.application.models import SiteRun
from banbo.application.multi_period import MultiPeriodSiteResult
from banbo.domain import (
    Direction,
    DocumentSource,
    FailureCode,
    FailureResult,
    ParseEvidence,
    ValidatedResult,
)
from banbo.reporting import (
    conflict_rejected_values,
    conflict_site_names,
    failure_site_names,
    merge_failure_report,
    merge_success_report,
    render_failure_report,
)
from banbo.storage.site_repository import SiteRecord

PERIOD = 289
SUB_A = SiteRecord(
    site_id="hw-9001",
    name="甲站",
    url="https://hw-9001.test/article",
    direction=Direction.TOP,
)
SUB_B = SiteRecord(
    site_id="hw-9002",
    name="乙站",
    url="https://hw-9002.test/article",
    direction=Direction.TOP,
)
SUB_C = SiteRecord(
    site_id="hw-9003",
    name="丙站",
    url="https://hw-9003.test/article",
    direction=Direction.TOP,
)


def _evidence(site: SiteRecord, value: str, period: int = PERIOD) -> ParseEvidence:
    return ParseEvidence(
        site_id=site.site_id,
        target_issue=period,
        value=value,
        document_id=f"{site.site_id}-doc",
        document_source=DocumentSource.PAGE,
        document_order=0,
        snippet=f"{period}期 绝杀半波 {value}",
        parser_name="anchor_segment",
        parser_version="1",
        direction=site.direction,
        anchor_passed=True,
        keyword_passed=True,
        same_record=True,
        boundary_issues=(period, period - 1, period - 2),
        block_id=f"{site.site_id}-doc:0:40",
        source_url=f"https://{site.site_id}.test/article",
    )


def _run(site: SiteRecord, value: str, period: int = PERIOD) -> SiteRun:
    return SiteRun(
        site=site,
        outcome=ValidatedResult(
            site_id=site.site_id,
            site_name=site.name,
            target_issue=period,
            value=value,
            direction=site.direction,
            evidence=_evidence(site, value, period),
            parser_version="1",
        ),
    )


def _failed_run(
    site: SiteRecord,
    message: str = "未找到289期专属证据",
    period: int = PERIOD,
) -> SiteRun:
    return SiteRun(
        site=site,
        outcome=FailureResult(
            site_id=site.site_id,
            target_issue=period,
            code=FailureCode.TARGET_PERIOD_MISSING,
            message=message,
        ),
    )


def _failure_line(
    name: str,
    url: str,
    reason: str,
    *,
    kind: str = "失败",
    period: int = PERIOD,
) -> str:
    return (
        f"{kind} {name} {url} 方向: top 期数: {period} "
        f"阶段: 目标定位 原因: {reason}"
    )


def _cache_file(
    path,
    *,
    issues: tuple[int, ...] = (PERIOD,),
    sites: list[dict] | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "issues": list(issues),
                "window_size": len(issues),
                "partial_issues": [],
                "sites": sites or [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# --- 成功TXT 合并语义 ---------------------------------------------------------


def test_subset_run_keeps_rows_of_sites_it_did_not_touch():
    existing = "红单\t甲站\n绿双\t乙站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n1\t绿双\t1\n"
    merge = merge_success_report(existing, PERIOD, [_run(SUB_C, "蓝单")])
    assert merge.conflicts == ()
    lines = merge.content.splitlines()
    assert "红单\t甲站" in lines
    assert "绿双\t乙站" in lines
    assert "蓝单\t丙站" in lines
    assert lines.count("") == 1
    assert "排名\t内容\t数量" in lines
    assert lines[-3:] == ["1\t红单\t1", "2\t绿双\t1", "3\t蓝单\t1"]


def test_rows_outside_site_config_survive_and_are_ranked():
    existing = (
        "红单\t甲站\n"
        "红双 站外手工行\n"
        "\n289期排行\n内容\t次数\t排名\n红单\t1\t1\n"
    )
    merge = merge_success_report(existing, PERIOD, [_run(SUB_B, "红双")])
    assert merge.conflicts == ()
    lines = merge.content.splitlines()
    assert "红双 站外手工行" in lines
    assert "红双\t乙站" in lines
    assert "内容\t次数\t排名" in lines
    assert lines[-2:] == ["红双\t2\t1", "红单\t1\t2"]


def test_conflicting_value_is_not_written_over():
    existing = "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n"
    merge = merge_success_report(existing, PERIOD, [_run(SUB_A, "蓝单")])
    assert merge.content == existing
    assert len(merge.conflicts) == 1
    assert merge.conflicts[0].site_name == "甲站"
    assert merge.conflicts[0].existing_values == ("红单",)
    assert merge.conflicts[0].new_value == "蓝单"
    assert merge.conflicts[0].source == "成功TXT"


def test_accept_verified_replaces_a_wrong_recorded_value():
    existing = "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n"
    merge = merge_success_report(
        existing,
        PERIOD,
        [_run(SUB_A, "蓝单")],
        known_values={"甲站": "红单"},
        accept_verified=True,
    )
    assert merge.conflicts == ()
    assert merge.replaced == {"甲站": ("红单",)}
    assert merge.cache_align == {"甲站": "蓝单"}
    lines = merge.content.splitlines()
    assert "蓝单\t甲站" in lines
    assert "红单\t甲站" not in lines
    assert lines[-1] == "1\t蓝单\t1"


def test_stale_cache_is_aligned_instead_of_conflicting():
    """TXT 与本次结果一致、缓存不同：缓存过期，按 TXT 对齐，不报冲突。"""

    existing = "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n"
    merge = merge_success_report(
        existing,
        PERIOD,
        [_run(SUB_A, "红单")],
        known_values={"甲站": "蓝单"},
    )
    assert merge.conflicts == ()
    assert merge.cache_align == {"甲站": "红单"}
    assert merge.content == existing


def test_cache_value_blocks_a_row_the_txt_never_had():
    merge = merge_success_report(
        "",
        PERIOD,
        [_run(SUB_A, "蓝单")],
        known_values={"甲站": "红单"},
    )
    assert merge.content == ""
    assert len(merge.conflicts) == 1
    assert merge.conflicts[0].source == "缓存"


def test_accept_verified_covers_the_cache_only_conflict():
    merge = merge_success_report(
        "",
        PERIOD,
        [_run(SUB_A, "蓝单")],
        known_values={"甲站": "红单"},
        accept_verified=True,
    )
    assert merge.conflicts == ()
    assert merge.cache_align == {"甲站": "蓝单"}
    assert "蓝单\t甲站" in merge.content.splitlines()


def test_same_value_is_idempotent():
    existing = "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n"
    merge = merge_success_report(existing, PERIOD, [_run(SUB_A, "红单")])
    assert merge.content == existing
    assert merge.conflicts == ()


def test_fresh_file_matches_full_renderer():
    from banbo.reporting import render_success_report

    runs = [_run(SUB_A, "红单"), _run(SUB_B, "红单"), _run(SUB_C, "蓝单")]
    merge = merge_success_report("", PERIOD, runs)
    assert merge.conflicts == ()
    assert merge.content == render_success_report(PERIOD, runs)


# --- 失败文件合并 -------------------------------------------------------------


def test_failure_merge_keeps_records_of_other_sites():
    existing = _failure_line("乙站", SUB_B.url, "未找到289期专属证据") + "\n"
    merged = merge_failure_report(existing, PERIOD, [_run(SUB_A, "红单")])
    assert merged == existing


def test_failure_merge_replaces_record_of_covered_site():
    existing = (
        _failure_line("甲站", SUB_A.url, "旧原因")
        + "\n\n"
        + _failure_line("乙站", SUB_B.url, "未找到289期专属证据")
        + "\n"
    )
    merged = merge_failure_report(
        existing, PERIOD, [_failed_run(SUB_A, "新原因"), _run(SUB_C, "绿双")]
    )
    assert "失败 乙站" in merged
    assert "旧原因" not in merged
    assert "新原因" in merged


def test_failure_merge_drops_everything_when_all_clear():
    existing = _failure_line("甲站", SUB_A.url, "未找到289期专属证据") + "\n"
    assert merge_failure_report(existing, PERIOD, [_run(SUB_A, "红单")]) == ""


def test_retained_site_is_visible_but_not_retryable():
    merged = merge_failure_report(
        "",
        PERIOD,
        [_failed_run(SUB_A)],
        retained={"甲站": "本次校验失败，已保留定稿值红单"},
    )
    assert merged.startswith("保留 甲站")
    assert "已保留定稿值红单" in merged
    # 「保留」不进重抓名单
    assert failure_site_names(merged, PERIOD) == ()
    assert conflict_site_names(merged, PERIOD) == ()


def test_conflict_records_are_not_retried():
    text = (
        _failure_line("甲站", SUB_A.url, "成功TXT已有不同结果，拒绝覆盖：甲站 红单 -> 蓝单")
        + "\n\n"
        + _failure_line("乙站", SUB_B.url, "未找到289期专属证据")
        + "\n"
    )
    assert failure_site_names(text, PERIOD) == ("甲站", "乙站")
    assert conflict_site_names(text, PERIOD) == ("甲站",)


# --- 入口级：证明 cli.main 真的走了合并数据流 -------------------------------


class _FakeRunner:
    runs: ClassVar[list[SiteRun]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def run_many(self, period, *, site_ids=None, max_workers=8, progress_callback=None):
        selected = list(site_ids or [run.site.site_id for run in self.runs])
        return [run for run in self.runs if run.site.site_id in selected]


def _run_cli(
    monkeypatch,
    tmp_path,
    runs: list[SiteRun],
    site_ids: list[str],
    *,
    extra_args: list[str] | None = None,
    sites: list[SiteRecord] | None = None,
):
    repository = cli.SiteRepository(sites or [SUB_A, SUB_B, SUB_C])
    monkeypatch.setattr(cli, "_load_runtime", lambda: (repository, [], None))
    monkeypatch.setattr(cli, "BASE_DIR", tmp_path)
    _FakeRunner.runs = runs
    monkeypatch.setattr(cli, "SinglePeriodRunner", _FakeRunner)
    args = [
        "--period",
        str(PERIOD),
        *[flag for site_id in site_ids for flag in ("--site-id", site_id)],
        "--success-dir",
        str(tmp_path),
        "--failure-dir",
        str(tmp_path),
        *(extra_args or []),
    ]
    if "--cache" not in args:
        args.append("--no-update-cache")
    return cli.main(args)


def test_cli_subset_run_keeps_full_official_txt(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n绿双\t乙站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n1\t绿双\t1\n",
        encoding="utf-8",
    )
    rc = _run_cli(monkeypatch, tmp_path, [_run(SUB_C, "蓝单")], ["hw-9003"])
    assert rc == 0
    text = success.read_text(encoding="utf-8")
    assert "红单\t甲站" in text
    assert "绿双\t乙站" in text
    assert "蓝单\t丙站" in text
    assert not (tmp_path / f"{PERIOD}期-半波-失败.txt").exists()


def test_cli_conflict_records_failure_and_keeps_old_value(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    existing = "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n"
    success.write_text(existing, encoding="utf-8")
    rc = _run_cli(monkeypatch, tmp_path, [_run(SUB_A, "蓝单")], ["hw-9001"])
    assert rc == 1
    assert success.read_text(encoding="utf-8") == existing
    failure_text = (tmp_path / f"{PERIOD}期-半波-失败.txt").read_text(encoding="utf-8")
    assert "失败 甲站" in failure_text
    assert "拒绝覆盖" in failure_text
    assert "阶段: 数据校验" in failure_text
    audit = (tmp_path / "audit" / f"{PERIOD}.jsonl").read_text(encoding="utf-8")
    record = json.loads(audit.splitlines()[-1])
    assert record["failure_code"] == "same_period_conflict"
    assert record["document_id"] == "hw-9001-doc"


def test_cli_accept_verified_rewrites_txt_and_cache(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n", encoding="utf-8"
    )
    cache = tmp_path / "cache.json"
    _cache_file(
        cache,
        sites=[{"name": "甲站", "values": {str(PERIOD): "红单"}, "failures": {}}],
    )
    rc = _run_cli(
        monkeypatch,
        tmp_path,
        [_run(SUB_A, "蓝单")],
        ["hw-9001"],
        extra_args=[
            "--accept-verified",
            "--cache",
            str(cache),
        ],
    )
    assert rc == 0
    assert "蓝单\t甲站" in success.read_text(encoding="utf-8")
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["sites"][0]["values"][str(PERIOD)] == "蓝单"


def test_cli_stale_cache_is_aligned_and_run_succeeds(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n", encoding="utf-8"
    )
    cache = tmp_path / "cache.json"
    _cache_file(
        cache,
        sites=[{"name": "甲站", "values": {str(PERIOD): "蓝单"}, "failures": {}}],
    )
    rc = _run_cli(
        monkeypatch,
        tmp_path,
        [_run(SUB_A, "红单")],
        ["hw-9001"],
        extra_args=["--cache", str(cache)],
    )
    assert rc == 0
    assert not (tmp_path / f"{PERIOD}期-半波-失败.txt").exists()
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["sites"][0]["values"][str(PERIOD)] == "红单"


def test_cli_cache_failure_is_not_reported_as_success(monkeypatch, tmp_path):
    def _explode(*args, **kwargs):
        raise RuntimeError("缓存写入模拟失败")

    monkeypatch.setattr(cli, "_prepare_cache_update", _explode)
    rc = _run_cli(
        monkeypatch,
        tmp_path,
        [_run(SUB_A, "红单")],
        ["hw-9001"],
        extra_args=["--cache", str(tmp_path / "cache.json")],
    )
    assert rc == 2
    # 正式 TXT 已写，但退出码不为 0，提示两边可能不一致
    assert (tmp_path / f"{PERIOD}期-半波.txt").exists()


def test_cli_covered_failure_writes_retained_record(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    existing = "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n"
    success.write_text(existing, encoding="utf-8")
    rc = _run_cli(monkeypatch, tmp_path, [_failed_run(SUB_A)], ["hw-9001"])
    assert rc == 1
    assert success.read_text(encoding="utf-8") == existing
    failure_text = (tmp_path / f"{PERIOD}期-半波-失败.txt").read_text(encoding="utf-8")
    assert failure_text.startswith("保留 甲站")
    assert failure_site_names(failure_text, PERIOD) == ()


def test_cli_retained_site_refills_missing_cache_value(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n", encoding="utf-8"
    )
    cache = tmp_path / "cache.json"
    _cache_file(cache, sites=[{"name": "甲站", "values": {}, "failures": {}}])
    rc = _run_cli(
        monkeypatch,
        tmp_path,
        [_failed_run(SUB_A)],
        ["hw-9001"],
        extra_args=["--cache", str(cache)],
    )
    assert rc == 1
    payload = json.loads(cache.read_text(encoding="utf-8"))
    row = payload["sites"][0]
    # 三个文件一致：TXT 红单、缓存红单、失败目录写「保留」
    assert row["values"][str(PERIOD)] == "红单"
    assert row["failures"] == {}
    assert "保留 甲站" in (tmp_path / f"{PERIOD}期-半波-失败.txt").read_text(
        encoding="utf-8"
    )


def test_cli_covered_failure_without_previous_row_is_reported(monkeypatch, tmp_path):
    rc = _run_cli(monkeypatch, tmp_path, [_failed_run(SUB_A)], ["hw-9001"])
    assert rc == 1
    assert not (tmp_path / f"{PERIOD}期-半波.txt").exists()
    failure_text = (tmp_path / f"{PERIOD}期-半波-失败.txt").read_text(encoding="utf-8")
    assert "失败 甲站" in failure_text


def test_cli_dirty_success_txt_aborts_without_writing(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    dirty = "红单\t甲站\n蓝单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n"
    success.write_text(dirty, encoding="utf-8")
    rc = _run_cli(monkeypatch, tmp_path, [_run(SUB_B, "红单")], ["hw-9002"])
    assert rc == 2
    assert success.read_text(encoding="utf-8") == dirty
    assert not (tmp_path / "audit").exists()
    assert not (tmp_path / f"{PERIOD}期-半波-失败.txt").exists()


def test_cli_period_mismatch_in_success_txt_aborts(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    dirty = "红单\t甲站\n\n288期排行\n排名\t内容\t数量\n1\t红单\t1\n"
    success.write_text(dirty, encoding="utf-8")
    rc = _run_cli(monkeypatch, tmp_path, [_run(SUB_B, "红单")], ["hw-9002"])
    assert rc == 2
    assert success.read_text(encoding="utf-8") == dirty


# --- 重试入口 ------------------------------------------------------------------


def _run_cli_retry(monkeypatch, tmp_path, failure_text: str, *, extra_args=None):
    failure_path = tmp_path / f"{PERIOD}期-半波-失败.txt"
    failure_path.write_text(failure_text, encoding="utf-8")
    repository = cli.SiteRepository([SUB_A, SUB_B])
    monkeypatch.setattr(cli, "_load_runtime", lambda: (repository, [], None))
    monkeypatch.setattr(cli, "BASE_DIR", tmp_path)
    _FakeRunner.runs = [_run(SUB_A, "红单")]
    monkeypatch.setattr(cli, "SinglePeriodRunner", _FakeRunner)
    args = [
        "--period",
        str(PERIOD),
        "--retry-failures",
        "--success-dir",
        str(tmp_path),
        "--failure-dir",
        str(tmp_path),
        *(extra_args or []),
    ]
    if "--cache" not in args:
        args.append("--no-update-cache")
    return cli.main(args)


def test_cli_retry_with_missing_cache_exits_2(monkeypatch, tmp_path):
    """缓存缺失时重试：TXT/审计照写，但建基准要全站，所以退出码 2。"""

    text = _failure_line("甲站", SUB_A.url, "未找到289期专属证据") + "\n"
    cache = tmp_path / "cache.json"
    rc = _run_cli_retry(
        monkeypatch, tmp_path, text, extra_args=["--cache", str(cache)]
    )
    assert rc == 2
    assert not cache.exists()
    assert (tmp_path / f"{PERIOD}期-半波.txt").exists()


def test_cli_retry_with_only_conflicts_returns_non_zero(monkeypatch, tmp_path):
    conflict = _failure_line(
        "甲站", SUB_A.url, "成功TXT已有不同结果，拒绝覆盖：甲站 红单 -> 蓝单"
    )
    rc = _run_cli_retry(monkeypatch, tmp_path, conflict + "\n")
    assert rc == 1
    assert not (tmp_path / f"{PERIOD}期-半波.txt").exists()


def test_cli_retry_runs_normal_failures_and_skips_conflicts(monkeypatch, tmp_path):
    text = (
        _failure_line("甲站", SUB_A.url, "未找到289期专属证据")
        + "\n\n"
        + _failure_line("乙站", SUB_B.url, "成功TXT已有不同结果，拒绝覆盖：乙站 红单 -> 蓝单")
        + "\n"
    )
    rc = _run_cli_retry(monkeypatch, tmp_path, text)
    assert rc == 0
    assert "红单\t甲站" in (tmp_path / f"{PERIOD}期-半波.txt").read_text(
        encoding="utf-8"
    )


def test_accept_keeps_the_existing_file_shape():
    """替一行值不能顺手把排行区的形状改掉（多一行空白或标题都不行）。"""

    existing = (
        "红单\t甲站\n"
        "蓝单\t乙站\n"
        "\n内容\t次数\t排名\n"
        "红单\t1\t1\n"
        "蓝单\t1\t2\n"
    )
    merge = merge_success_report(
        existing, PERIOD, [_run(SUB_A, "蓝单")], accept_verified=True
    )
    assert merge.content.splitlines() == [
        "蓝单\t甲站",
        "蓝单\t乙站",
        "",
        "内容\t次数\t排名",
        "蓝单\t2\t1",
    ]


def test_retained_line_survives_a_second_round():
    """冲突→保留→再失败：上一次被拒的新值不能因为换成了「保留」行就丢。"""

    text = (
        "保留 甲站 https://hw-9001.test/article 方向: top 期数: 289 "
        "阶段: 指定期数校验 原因: 本次校验失败，已保留定稿值红单；"
        "上次拒绝的新值为蓝单\n"
    )
    assert conflict_rejected_values(text, PERIOD) == {"甲站": "蓝单"}

    merged = merge_failure_report(
        text,
        PERIOD,
        [_failed_run(SUB_A)],
        retained={"甲站": "本次校验失败，已保留定稿值红单；上次拒绝的新值为蓝单"},
    )
    assert "上次拒绝的新值为蓝单" in merged
    assert conflict_rejected_values(merged, PERIOD) == {"甲站": "蓝单"}


def test_cli_retained_two_rounds_keeps_the_rejected_value(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n", encoding="utf-8"
    )
    failure_path = tmp_path / f"{PERIOD}期-半波-失败.txt"
    failure_path.write_text(
        "保留 甲站 https://hw-9001.test/article 方向: top 期数: 289 "
        "阶段: 指定期数校验 原因: 本次校验失败，已保留定稿值红单；"
        "上次拒绝的新值为蓝单\n",
        encoding="utf-8",
    )
    rc = _run_cli(monkeypatch, tmp_path, [_failed_run(SUB_A)], ["hw-9001"])
    assert rc == 1
    assert "上次拒绝的新值为蓝单" in failure_path.read_text(encoding="utf-8")


def test_cli_accept_verified_writes_old_values_to_audit(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n", encoding="utf-8"
    )
    cache = tmp_path / "cache.json"
    _cache_file(
        cache,
        sites=[{"name": "甲站", "values": {str(PERIOD): "蓝单"}, "failures": {}}],
    )
    rc = _run_cli(
        monkeypatch,
        tmp_path,
        [_run(SUB_A, "绿双")],
        ["hw-9001"],
        extra_args=["--accept-verified", "--cache", str(cache)],
    )
    assert rc == 0
    journal = (tmp_path / "audit" / f"reconcile-{PERIOD}.jsonl").read_text(
        encoding="utf-8"
    )
    entry = json.loads(journal.splitlines()[-1])
    assert entry["action"] == "accept_verified"
    assert entry["site_name"] == "甲站"
    assert entry["old_txt_value"] == "红单"
    assert entry["old_cache_value"] == "蓝单"
    assert entry["new_value"] == "绿双"
    assert entry["parser_version"] == "1"
    assert entry["document_id"] == "hw-9001-doc"
    assert entry["run_id"]
    # 证据要能证明新值来自哪一行，而不只是“改成了什么”
    assert entry["snippet"] == f"{PERIOD}期 绝杀半波 绿双"
    assert entry["block_id"] == "hw-9001-doc:0:40"
    assert entry["document_source"] == "page"
    assert entry["source_url"] == "https://hw-9001.test/article"
    assert entry["boundary_issues"] == [PERIOD, PERIOD - 1, PERIOD - 2]
    assert entry["cache_committed"] is True


def test_cli_accept_requires_explicit_site(monkeypatch, tmp_path):
    repository = cli.SiteRepository([SUB_A])
    monkeypatch.setattr(cli, "_load_runtime", lambda: (repository, [], None))
    monkeypatch.setattr(cli, "BASE_DIR", tmp_path)
    _FakeRunner.runs = [_run(SUB_A, "红单")]
    monkeypatch.setattr(cli, "SinglePeriodRunner", _FakeRunner)
    rc = cli.main(
        [
            "--period",
            str(PERIOD),
            "--accept-verified",
            "--success-dir",
            str(tmp_path),
            "--failure-dir",
            str(tmp_path),
            "--no-update-cache",
        ]
    )
    assert rc == 2
    assert not (tmp_path / f"{PERIOD}期-半波.txt").exists()


def test_cli_retained_value_reaches_a_new_period_cache(monkeypatch, tmp_path):
    """新期推进（advance）分支也要把保留站点的定稿值写进缓存。"""

    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n绿双\t乙站\n蓝单\t丙站\n"
        "\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n1\t绿双\t1\n1\t蓝单\t1\n",
        encoding="utf-8",
    )
    cache = tmp_path / "cache.json"
    _cache_file(
        cache,
        issues=(PERIOD - 1,),
        sites=[
            {"name": "甲站", "values": {}, "failures": {}},
            {"name": "乙站", "values": {}, "failures": {}},
            {"name": "丙站", "values": {}, "failures": {}},
        ],
    )
    rc = _run_cli(
        monkeypatch,
        tmp_path,
        [_run(SUB_A, "红单"), _run(SUB_B, "绿双"), _failed_run(SUB_C)],
        ["hw-9001", "hw-9002", "hw-9003"],
        extra_args=["--cache", str(cache)],
    )
    assert rc == 1
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["issues"] == [PERIOD]
    rows = {row["name"]: row for row in payload["sites"]}
    # 甲/乙 本期验证成功；丙 本次失败但本期有定稿值 → 缓存里是定稿值
    assert rows["甲站"]["values"][str(PERIOD)] == "红单"
    assert rows["丙站"]["values"][str(PERIOD)] == "蓝单"
    assert rows["丙站"]["failures"] == {}


def test_cli_retained_value_reaches_a_missing_cache_file(monkeypatch, tmp_path):
    """缓存文件不存在（建基准分支）时，全站跑也要写入保留站点的定稿值。"""

    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n绿双\t乙站\n蓝单\t丙站\n"
        "\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n1\t绿双\t1\n1\t蓝单\t1\n",
        encoding="utf-8",
    )
    cache = tmp_path / "cache.json"
    assert not cache.exists()
    rc = _run_cli(
        monkeypatch,
        tmp_path,
        [_run(SUB_A, "红单"), _run(SUB_B, "绿双"), _failed_run(SUB_C)],
        ["hw-9001", "hw-9002", "hw-9003"],
        extra_args=["--cache", str(cache)],
    )
    assert rc == 1
    payload = json.loads(cache.read_text(encoding="utf-8"))
    rows = {item["name"]: item for item in payload["sites"]}
    assert rows["甲站"]["values"][str(PERIOD)] == "红单"
    assert rows["丙站"]["values"][str(PERIOD)] == "蓝单"
    assert rows["丙站"]["failures"] == {}


def test_cli_missing_cache_refuses_a_partial_baseline(monkeypatch, tmp_path):
    """缓存文件不存在时不能用子集跑种下部分基准。"""

    cache = tmp_path / "cache.json"
    rc = _run_cli(
        monkeypatch,
        tmp_path,
        [_run(SUB_A, "红单")],
        ["hw-9001"],
        extra_args=["--cache", str(cache)],
    )
    assert rc == 2
    assert not cache.exists()
    # 正式 TXT 仍然写出来，只是缓存没建
    assert (tmp_path / f"{PERIOD}期-半波.txt").exists()


def test_cli_new_period_single_site_accept_fails_loud(monkeypatch, tmp_path):
    """新期（窗口外）单站 accept：TXT 能改，但缓存推进要全站，必须报错而不是静默。"""

    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n", encoding="utf-8"
    )
    cache = tmp_path / "cache.json"
    _cache_file(
        cache,
        issues=(PERIOD - 1,),
        sites=[
            {"name": "甲站", "values": {}, "failures": {}},
            {"name": "乙站", "values": {}, "failures": {}},
            {"name": "丙站", "values": {}, "failures": {}},
        ],
    )
    rc = _run_cli(
        monkeypatch,
        tmp_path,
        [_run(SUB_A, "蓝单")],
        ["hw-9001"],
        extra_args=["--accept-verified", "--cache", str(cache)],
    )
    assert rc == 2
    # TXT 的那一行已被 accept 改掉
    assert "蓝单\t甲站" in success.read_text(encoding="utf-8")
    # 缓存窗口没有推进，也没有被写成部分基准
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["issues"] == [PERIOD - 1]


def test_cli_accept_a_brand_new_row_is_labelled_accept_verified(monkeypatch, tmp_path):
    """TXT 原本没有这行、缓存有不同值：accept 后 action 也要是 accept_verified。"""

    cache = tmp_path / "cache.json"
    _cache_file(
        cache,
        sites=[{"name": "甲站", "values": {str(PERIOD): "红单"}, "failures": {}}],
    )
    rc = _run_cli(
        monkeypatch,
        tmp_path,
        [_run(SUB_A, "蓝单")],
        ["hw-9001"],
        extra_args=["--accept-verified", "--cache", str(cache)],
    )
    assert rc == 0
    entry = json.loads(
        (tmp_path / "audit" / f"reconcile-{PERIOD}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert entry["action"] == "accept_verified"
    assert entry["old_txt_value"] is None
    assert entry["old_cache_value"] == "红单"
    assert entry["cache_committed"] is True


def test_cli_reconcile_marks_cache_not_committed_when_write_fails(
    monkeypatch, tmp_path
):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n", encoding="utf-8"
    )

    def _explode(*args, **kwargs):
        raise RuntimeError("缓存写入模拟失败")

    monkeypatch.setattr(cli, "_prepare_cache_update", _explode)
    rc = _run_cli(
        monkeypatch,
        tmp_path,
        [_run(SUB_A, "蓝单")],
        ["hw-9001"],
        extra_args=["--accept-verified", "--cache", str(tmp_path / "cache.json")],
    )
    assert rc == 2
    entry = json.loads(
        (tmp_path / "audit" / f"reconcile-{PERIOD}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert entry["cache_committed"] is False
    assert "蓝单\t甲站" in success.read_text(encoding="utf-8")


def test_cli_reconcile_marks_cache_not_committed_when_skipped(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n", encoding="utf-8"
    )
    rc = _run_cli(
        monkeypatch,
        tmp_path,
        [_run(SUB_A, "蓝单")],
        ["hw-9001"],
        extra_args=["--accept-verified"],
    )
    assert rc == 0
    entry = json.loads(
        (tmp_path / "audit" / f"reconcile-{PERIOD}.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[-1]
    )
    assert entry["cache_committed"] is False


def test_cli_retained_line_carries_the_previously_rejected_value(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n", encoding="utf-8"
    )
    failure_path = tmp_path / f"{PERIOD}期-半波-失败.txt"
    failure_path.write_text(
        _failure_line("甲站", SUB_A.url, "成功TXT已有不同结果，拒绝覆盖：甲站 红单 -> 蓝单")
        + "\n",
        encoding="utf-8",
    )
    rc = _run_cli(monkeypatch, tmp_path, [_failed_run(SUB_A)], ["hw-9001"])
    assert rc == 1
    text = failure_path.read_text(encoding="utf-8")
    assert text.startswith("保留 甲站")
    assert "上次拒绝的新值为蓝单" in text


# --- 多期入口 ------------------------------------------------------------------


def _multi_run_periods(payload):
    def _fake(runner, periods, **kwargs):
        return payload

    return _fake


def _run_multi(monkeypatch, tmp_path, results, periods, *, cache=None):
    monkeypatch.setattr(multi_cli, "run_periods", _multi_run_periods(results))
    monkeypatch.setattr(
        multi_cli, "_load_runtime", lambda: (cli.SiteRepository([SUB_A]), [], None)
    )
    monkeypatch.setattr(multi_cli, "BASE_DIR", tmp_path)
    return multi_cli.main(
        [
            "--periods",
            *[str(period) for period in periods],
            "--success-dir",
            str(tmp_path),
            "--failure-dir",
            str(tmp_path),
            "--cache",
            str(cache or tmp_path / "cache.json"),
        ]
    )


def test_multi_period_conflict_reaches_summary_and_exit(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    existing = "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n"
    success.write_text(existing, encoding="utf-8")

    results = (
        MultiPeriodSiteResult(
            "hw-9001",
            (_run(SUB_A, "红单", 288), _run(SUB_A, "蓝单", PERIOD)),
        ),
    )
    rc = _run_multi(monkeypatch, tmp_path, results, (288, PERIOD))

    assert rc == 1
    assert success.read_text(encoding="utf-8") == existing
    failure_text = (tmp_path / f"{PERIOD}期-半波-失败.txt").read_text(encoding="utf-8")
    assert "失败 甲站" in failure_text
    assert "拒绝覆盖" in failure_text
    summary = (
        tmp_path / f"多期-288-{PERIOD}-半波-全部失败.txt"
    ).read_text(encoding="utf-8")
    # 站点在 288 期成功，也必须在汇总里列出 289 期的失败
    assert "失败 甲站" in summary
    assert f"期数: {PERIOD}" in summary


def test_multi_period_partial_failure_is_not_hidden(monkeypatch, tmp_path):
    results = (
        MultiPeriodSiteResult(
            "hw-9001",
            (_run(SUB_A, "红单", 288), _failed_run(SUB_A, "未找到289期专属证据")),
        ),
    )
    rc = _run_multi(monkeypatch, tmp_path, results, (288, PERIOD))

    assert rc == 1
    summary = (
        tmp_path / f"多期-288-{PERIOD}-半波-全部失败.txt"
    ).read_text(encoding="utf-8")
    assert f"期数: {PERIOD}" in summary
    assert "红单\t甲站" in (tmp_path / "288期-半波.txt").read_text(encoding="utf-8")


def test_multi_period_reads_cache_as_conflict_source(monkeypatch, tmp_path):
    """多期不写缓存，但必须读缓存：否则写下去的正式值会和缓存打架。"""

    cache = tmp_path / "cache.json"
    _cache_file(
        cache,
        sites=[{"name": "甲站", "values": {str(PERIOD): "红单"}, "failures": {}}],
    )
    results = (MultiPeriodSiteResult("hw-9001", (_run(SUB_A, "蓝单"),)),)
    rc = _run_multi(monkeypatch, tmp_path, results, (PERIOD,), cache=cache)

    assert rc == 1
    assert not (tmp_path / f"{PERIOD}期-半波.txt").exists()
    failure_text = (tmp_path / f"{PERIOD}期-半波-失败.txt").read_text(encoding="utf-8")
    assert "拒绝覆盖" in failure_text
    assert "缓存" in failure_text


def test_multi_period_retained_site_is_labelled(monkeypatch, tmp_path):
    success = tmp_path / f"{PERIOD}期-半波.txt"
    success.write_text(
        "红单\t甲站\n\n289期排行\n排名\t内容\t数量\n1\t红单\t1\n", encoding="utf-8"
    )
    results = (
        MultiPeriodSiteResult(
            "hw-9001",
            (_run(SUB_A, "红单", 288), _failed_run(SUB_A, "未找到289期专属证据")),
        ),
    )
    _run_multi(monkeypatch, tmp_path, results, (288, PERIOD))
    summary = (
        tmp_path / f"多期-288-{PERIOD}-半波-全部失败.txt"
    ).read_text(encoding="utf-8")
    # 汇总与每期失败TXT 用同一个「保留」标签，不写成「失败」
    assert "保留 甲站" in summary
    assert "失败 甲站" not in summary


def test_render_failure_report_still_formats_single_site():
    text = render_failure_report(PERIOD, [_failed_run(SUB_A)])
    assert text.startswith("失败 甲站 https://hw-9001.test/article 方向: top 期数: 289")
