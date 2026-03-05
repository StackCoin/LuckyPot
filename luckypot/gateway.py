import asyncio
import json
from typing import Callable, Awaitable

from loguru import logger


EventHandler = Callable[[dict], Awaitable[None]]


class StackCoinGateway:
    def __init__(
        self,
        ws_url: str,
        token: str,
        last_event_id: int = 0,
        on_event_id: Callable[[int], None] | None = None,
    ):
        self._ws_url = ws_url.rstrip("/")
        self._token = token
        self._handlers: dict[str, list[EventHandler]] = {}
        self._last_event_id = last_event_id
        self._on_event_id = on_event_id
        self._ws = None
        self._running = False
        self._ref_counter = 0

    def on(self, event_type: str):
        def decorator(func: EventHandler):
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(func)
            return func

        return decorator

    def register_handler(self, event_type: str, handler: EventHandler):
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    async def connect(self):
        import websockets

        self._running = True

        while self._running:
            try:
                url = f"{self._ws_url}?token={self._token}&vsn=2.0.0"

                async with websockets.connect(url) as ws:
                    self._ws = ws
                    logger.info("Connected to StackCoin gateway")

                    await self._join_channel(ws)

                    heartbeat_task = asyncio.create_task(self._heartbeat(ws))
                    try:
                        async for raw_msg in ws:
                            msg = json.loads(raw_msg)
                            await self._handle_message(msg)
                    finally:
                        heartbeat_task.cancel()

            except Exception as e:
                logger.error(f"Gateway connection error: {e}")
                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)

    async def _join_channel(self, ws):
        """Join the user:self channel with event replay."""
        self._ref_counter += 1
        join_msg = json.dumps(
            [
                None,
                str(self._ref_counter),
                "user:self",
                "phx_join",
                {"last_event_id": self._last_event_id},
            ]
        )
        await ws.send(join_msg)

        reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if reply[3] == "phx_reply" and reply[4].get("status") == "ok":
            logger.info(
                f"Joined user channel (replaying from event {self._last_event_id})"
            )
        else:
            raise Exception(f"Failed to join channel: {reply}")

    async def _heartbeat(self, ws):
        """Send periodic heartbeats to keep the connection alive."""
        while True:
            await asyncio.sleep(30)
            self._ref_counter += 1
            hb = json.dumps([None, str(self._ref_counter), "phoenix", "heartbeat", {}])
            await ws.send(hb)

    async def _handle_message(self, msg):
        """Dispatch an incoming message to registered handlers."""
        if len(msg) < 5:
            return

        event_name = msg[3]
        payload = msg[4]

        if event_name == "event":
            event_type = payload.get("type", "")
            event_id = payload.get("id", 0)

            if event_id > self._last_event_id:
                self._last_event_id = event_id

            for handler in self._handlers.get(event_type, []):
                try:
                    await handler(payload)
                except Exception as e:
                    logger.error(f"Error in handler for {event_type}: {e}")

            if event_id > 0 and self._on_event_id:
                try:
                    self._on_event_id(event_id)
                except Exception as e:
                    logger.error(f"Failed to persist event ID {event_id}: {e}")

    def stop(self):
        """Signal the gateway to stop reconnecting and disconnect."""
        self._running = False
