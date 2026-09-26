"""Tests for boomarr.events (live events and the in-memory log view)."""

import asyncio
import logging
import threading

from boomarr.events import EventBus, LogBuffer


class TestEventBus:
    def test_publish_without_loop_is_ignored(self) -> None:
        bus = EventBus()
        bus.publish("x", 1)  # no loop bound yet
        assert bus.subscriber_count == 0

    def test_publish_from_loop_and_threads(self) -> None:
        bus = EventBus()

        async def main() -> list[dict[str, object]]:
            bus.bind(asyncio.get_running_loop())
            async with bus.subscribe() as queue:
                assert bus.subscriber_count == 1
                bus.publish("direct", {"a": 1})
                thread = threading.Thread(target=bus.publish, args=("thread", 2))
                thread.start()
                thread.join()
                first = await asyncio.wait_for(queue.get(), 1)
                second = await asyncio.wait_for(queue.get(), 1)
            assert bus.subscriber_count == 0
            return [first, second]

        first, second = asyncio.run(main())
        assert first["type"] == "direct"
        assert first["data"] == {"a": 1}
        assert second["type"] == "thread"
        assert int(second["id"]) > int(first["id"])  # ty: ignore[invalid-argument-type]

    def test_closed_loop_and_full_queue(self) -> None:
        bus = EventBus()

        async def main() -> None:
            bus.bind(asyncio.get_running_loop())
            async with bus.subscribe() as queue:
                for i in range(300):
                    bus.publish("spam", i)
                assert queue.qsize() == queue.maxsize

        asyncio.run(main())
        bus.publish("after", None)  # loop closed: ignored

    def test_publish_while_loop_shuts_down(self) -> None:
        bus = EventBus()
        loop = asyncio.new_event_loop()
        bus.bind(loop)

        def closed_call(*_: object) -> None:
            raise RuntimeError("Event loop is closed")

        loop.call_soon_threadsafe = closed_call  # ty: ignore[invalid-assignment]
        bus.publish("x", None)
        loop.close()


class TestLogBuffer:
    def test_entries_and_levels(self) -> None:
        bus = EventBus()
        buffer = LogBuffer(bus, capacity=3)
        logger = logging.getLogger("boomarr.test.events")
        logger.addHandler(buffer)
        logger.setLevel(logging.DEBUG)
        try:
            logger.debug("one")
            logger.info("two")
            logger.warning("three")
            try:
                raise ValueError("boom")
            except ValueError:
                logger.exception("four")
        finally:
            logger.removeHandler(buffer)
        entries = buffer.entries()
        assert [e["message"].splitlines()[0] for e in entries] == [
            "two",
            "three",
            "four",
        ]
        assert "ValueError: boom" in entries[-1]["message"]
        assert [e["level"] for e in buffer.entries(min_level="warning")] == [
            "WARNING",
            "ERROR",
        ]
        assert len(buffer.entries(limit=1)) == 1
        assert buffer.entries(min_level="nonsense")[0]["message"] == "two"

    def test_without_bus(self) -> None:
        buffer = LogBuffer()
        buffer.emit(
            logging.LogRecord("x", logging.INFO, __file__, 1, "hi %s", ("there",), None)
        )
        assert buffer.entries()[0]["message"] == "hi there"
