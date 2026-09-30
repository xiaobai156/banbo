from __future__ import annotations

from threading import Event, Lock
from typing import Callable, Generic, Hashable, TypeVar


_Value = TypeVar("_Value")


class RequestCache(Generic[_Value]):
    def __init__(self) -> None:
        self._values: dict[Hashable, _Value] = {}
        self._errors: dict[Hashable, BaseException] = {}
        self._inflight: dict[Hashable, Event] = {}
        self._lock = Lock()

    def get_or_create(
        self,
        key: Hashable,
        factory: Callable[[], _Value],
    ) -> _Value:
        while True:
            with self._lock:
                if key in self._values:
                    return self._values[key]
                if key in self._errors:
                    raise self._errors[key]
                event = self._inflight.get(key)
                if event is None:
                    event = Event()
                    self._inflight[key] = event
                    owner = True
                else:
                    owner = False
            if owner:
                break
            event.wait()

        try:
            value = factory()
        except BaseException as exc:
            with self._lock:
                self._errors[key] = exc
                self._inflight.pop(key, None)
                event.set()
            raise

        with self._lock:
            self._values[key] = value
            self._inflight.pop(key, None)
            event.set()
        return value

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._errors.clear()
