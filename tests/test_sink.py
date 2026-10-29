import asyncio

from busylib.exceptions import BusyBarAPIError

from agentbar.config import BusyBarConfig
from agentbar.sink import BusyBarSink


class FakeClient:
    def __init__(self):
        self.calls = []
        self.fail_409 = False

    async def display_draw(self, payload):
        if self.fail_409:
            raise BusyBarAPIError("Not drawn due to low priority", status_code=409)
        self.calls.append(("draw", [e["id"] for e in payload["elements"]]))

    async def display_clear(self, element_ids=None, application_name=None):
        self.calls.append(("clear", element_ids))


def el(i, text="x"):
    return {"id": i, "type": "text", "text": text}


def test_diffing_and_409_yield():
    now = [0.0]
    client = FakeClient()
    sink = BusyBarSink(BusyBarConfig(), retry_s=5, client=client, clock=lambda: now[0])

    async def go():
        await sink.apply({"10": el("10"), "11": el("11")})
        await sink.apply({"10": el("10"), "11": el("11")})  # no change -> no call
        await sink.apply({"10": el("10", "y")})  # 11 removed, 10 changed
        client.fail_409 = True
        await sink.apply({"10": el("10", "z")})
        assert sink.blocked
        client.fail_409 = False
        now[0] = 1.0
        await sink.apply({"10": el("10", "z")})  # still inside retry window
        now[0] = 6.0
        await sink.apply({"10": el("10", "z")})  # retried, full redraw

    asyncio.run(go())
    assert client.calls == [
        ("draw", ["10", "11"]),
        ("clear", ["11"]),
        ("draw", ["10"]),
        ("clear", None),  # hide our app on 409
        ("draw", ["10"]),
    ]
    assert not sink.blocked
