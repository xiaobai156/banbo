import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

from banbo.fetch.request_cache import RequestCache


class RequestCacheTest(unittest.TestCase):
    def test_concurrent_callers_share_one_factory_result(self):
        cache = RequestCache()
        call_count = 0
        count_lock = threading.Lock()

        def factory():
            nonlocal call_count
            with count_lock:
                call_count += 1
            time.sleep(0.02)
            return object()

        with ThreadPoolExecutor(max_workers=8) as executor:
            values = list(
                executor.map(
                    lambda _: cache.get_or_create("same", factory),
                    range(16),
                )
            )

        self.assertEqual(1, call_count)
        self.assertTrue(all(value is values[0] for value in values))

    def test_failed_factory_does_not_poison_cache(self):
        cache = RequestCache()

        with self.assertRaisesRegex(RuntimeError, "first"):
            cache.get_or_create("key", lambda: (_ for _ in ()).throw(RuntimeError("first")))

        self.assertEqual("ok", cache.get_or_create("key", lambda: "ok"))


if __name__ == "__main__":
    unittest.main()
