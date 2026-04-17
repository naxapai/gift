import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestRedisTopicsV5(unittest.TestCase):
    def test_v5_topics_are_present_in_runtime(self) -> None:
        spec = (ROOT / "config" / "contracts" / "v5" / "redis_topics_structure_v1.3.txt").read_text(encoding="utf-8")
        core = (ROOT / "core.py").read_text(encoding="utf-8")
        self.assertIn("stream:metrics.updated", spec)
        self.assertIn("stream:signal.created", spec)
        self.assertIn("stream:market.status", spec)
        self.assertIn("stream:market.status.updated", spec)
        self.assertIn("stream:metrics.updated", core)
        self.assertIn("stream:signal.created", core)
        self.assertIn("stream:market.status", core)
        self.assertIn("stream:market.status.updated", core)
        self.assertIn("dedupe:tg:", core)


if __name__ == "__main__":
    unittest.main()
