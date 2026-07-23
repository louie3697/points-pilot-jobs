import asyncio

from scrapers.delta import DeltaScraper


def test_close_awaits_nodriver_connection_before_closing_event_loop():
    scraper = DeltaScraper()
    loop = asyncio.new_event_loop()
    scraper._loop = loop
    events = []

    class _Browser:
        def stop(self):
            events.append("stop-scheduled")
            loop.create_task(self.aclose())

        async def aclose(self):
            await asyncio.sleep(0)
            events.append("connection-closed")

    scraper._browser = _Browser()

    scraper.close()

    assert events == ["connection-closed"]
    assert loop.is_closed()
    assert scraper._browser is None
    assert scraper._loop is None


def test_close_cancels_and_drains_remaining_scraper_loop_tasks():
    scraper = DeltaScraper()
    loop = asyncio.new_event_loop()
    scraper._loop = loop
    events = []

    async def background_listener():
        try:
            await asyncio.Event().wait()
        finally:
            events.append("listener-drained")

    task = loop.create_task(background_listener())
    loop.run_until_complete(asyncio.sleep(0))

    scraper.close()

    assert task.done()
    assert task.cancelled()
    assert events == ["listener-drained"]
    assert loop.is_closed()
