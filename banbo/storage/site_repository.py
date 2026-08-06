from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from banbo.domain.models import Direction


@dataclass(frozen=True)
class SiteRecord:
    site_id: str
    name: str
    url: str
    direction: Direction
    second_click: bool = False
    shared_url_group: str | None = None


class SiteRepository:
    def __init__(self, records: Iterable[SiteRecord]) -> None:
        items = tuple(records)
        self._validate(items)
        self._records = items
        self._by_id = {item.site_id: item for item in items}

    @classmethod
    def from_json(cls, path: str | Path) -> "SiteRepository":
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        raw_sites = payload.get("sites") if isinstance(payload, dict) else payload
        if not isinstance(raw_sites, list):
            raise ValueError("站点配置必须是数组或包含sites数组的对象")
        records: list[SiteRecord] = []
        for item in raw_sites:
            raw_direction = item.get("direction", item.get("pick"))
            if raw_direction is None:
                raise ValueError(f"站点方向缺失：{item.get('name', '')}")
            records.append(
                SiteRecord(
                    site_id=str(item["site_id"]),
                    name=str(item["name"]),
                    url=str(item["url"]),
                    direction=Direction(str(raw_direction)),
                    second_click=bool(item.get("second_click", False)),
                    shared_url_group=(
                        None
                        if item.get("shared_url_group") is None
                        else str(item["shared_url_group"]).strip() or None
                    ),
                )
            )
        return cls(records)

    def all(self) -> tuple[SiteRecord, ...]:
        return self._records

    def get(self, site_id: str) -> SiteRecord:
        try:
            return self._by_id[site_id]
        except KeyError as exc:
            raise KeyError(f"未知站点：{site_id}") from exc

    @staticmethod
    def _validate(records: tuple[SiteRecord, ...]) -> None:
        ids = [item.site_id for item in records]
        names = [item.name for item in records]
        urls = [item.url for item in records]
        if any(not item for item in ids + names + urls):
            raise ValueError("站点ID、名称和URL不能为空")
        if len(ids) != len(set(ids)):
            raise ValueError("站点ID重复")
        if len(names) != len(set(names)):
            raise ValueError("站点名称重复")
        records_by_url: dict[str, list[SiteRecord]] = {}
        for item in records:
            records_by_url.setdefault(item.url, []).append(item)
        for url, same_url_records in records_by_url.items():
            if len(same_url_records) <= 1:
                continue
            groups = {
                item.shared_url_group for item in same_url_records
            }
            if len(groups) != 1 or None in groups:
                raise ValueError(f"站点URL重复：{url}")
        for item in records:
            parsed = urlparse(item.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"站点URL无效：{item.site_id}")
