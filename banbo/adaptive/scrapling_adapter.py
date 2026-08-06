from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from banbo.domain.models import Document


class AdaptiveMatchRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class AdaptiveOptions:
    enabled: bool = False
    shadow: bool = False


@dataclass(frozen=True)
class StructureProfile:
    status: str
    selectors: tuple[str, ...] = ()
    structure_fingerprint: str = ""


Locator = Callable[[Sequence[Document], StructureProfile], Sequence[Document]]


class ScraplingAdapter:
    """只定位候选文档，不解析期数、半波或方向。"""

    def __init__(self, locator: Locator | None = None) -> None:
        self._locator = locator

    def locate(
        self,
        documents: Sequence[Document],
        profile: StructureProfile | None,
        *,
        options: AdaptiveOptions | None = None,
    ) -> tuple[Document, ...]:
        options = options or AdaptiveOptions()
        if not options.enabled:
            return ()
        if profile is None or profile.status != "trusted":
            raise AdaptiveMatchRejected("没有可信结构档案")
        if self._locator is None:
            raise AdaptiveMatchRejected("未配置Scrapling结构定位器")
        candidates = tuple(self._locator(documents, profile))
        known = {document.document_id for document in documents}
        if any(document.document_id not in known for document in candidates):
            raise AdaptiveMatchRejected("结构定位器返回了原始文档之外的对象")
        return candidates
