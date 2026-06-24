import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.markets import build_live_orderbook_payload

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/orderbooks/{market_id}")
async def live_orderbook(websocket: WebSocket, market_id: int) -> None:
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(await build_live_orderbook_payload(market_id))
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return
