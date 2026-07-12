import unittest

from modules.conversation_crawler import crawl_public_webpage


class MockSeparationTests(unittest.TestCase):
    def test_real_crawl_does_not_fallback_to_local_sample(self):
        def failing_fetcher(url):
            raise RuntimeError("network unavailable")

        with self.assertRaisesRegex(RuntimeError, "network unavailable"):
            crawl_public_webpage("https://www.agri.cn/public.htm", fetcher=failing_fetcher)


if __name__ == "__main__":
    unittest.main()
