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


class RawClient(FakeClient):
    """Also records raw api_request draws, the path for icon bitmaps."""

    def __init__(self):
        super().__init__()
        self.raw = []

    async def api_request(self, method, path, json_payload=None):
        if self.fail_409:
            raise BusyBarAPIError("Not drawn due to low priority", status_code=409)
        self.raw.append((method, path, json_payload))


ICON = {"id": "105", "z_index": 105, "type": "xpmbitmap", "display": "front", "x": 20, "y": 3, "data": "! XPM2\n"}
BAR = {
    "id": "100",
    "z_index": 100,
    "type": "rectangle",
    "display": "front",
    "x": 16,
    "y": 14,
    "width": 18,
    "height": 2,
    "fill": "gradient_h",
    "fill_colors": ["#00C850", "#00C850"],
    "border_width": 0,
}


def test_bitmaps_go_through_the_raw_request_unchanged():
    client = RawClient()
    sink = BusyBarSink(BusyBarConfig(), retry_s=5, client=client)
    asyncio.run(sink.apply({"100": BAR, "105": ICON}))
    assert client.calls == []  # not display_draw, which would reject the bitmap
    [(method, path, payload)] = client.raw
    assert (method, path, payload["application_name"], payload["priority"]) == (
        "POST",
        "/api/display/draw",
        "agentbar",
        50,
    )
    bar, icon = payload["elements"]
    assert icon == ICON  # passed through as is
    assert bar["id"] == "100" and bar["fill_colors"] != BAR["fill_colors"]  # normalised by busylib (RGBA)


def test_bitmap_only_draw_and_409_yield():
    client = RawClient()
    sink = BusyBarSink(BusyBarConfig(), retry_s=5, client=client)

    async def go():
        await sink.apply({"105": ICON})
        client.fail_409 = True
        await sink.apply({"105": {**ICON, "x": 21}})

    asyncio.run(go())
    assert [p["elements"] for _, _, p in client.raw] == [[ICON]]
    assert sink.blocked and client.calls == [("clear", None)]
