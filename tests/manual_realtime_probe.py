import asyncio
import json
import sys
from pathlib import Path

import websockets
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.realtime_asr_service import build_realtime_asr_url


async def main() -> None:
    load_dotenv("backend/.env")
    provider_url, _ = build_realtime_asr_url()
    print("Connecting to Tencent realtime ASR...")
    try:
        async with websockets.connect(provider_url, max_size=2 * 1024 * 1024) as socket:
            handshake = json.loads(await asyncio.wait_for(socket.recv(), timeout=12))
            print(f"Handshake code: {handshake.get('code')}")
            for _ in range(25):
                await socket.send(bytes(1280))  # 40 ms of 16 kHz mono PCM silence.
                await asyncio.sleep(0.04)
            await socket.send(json.dumps({"type": "end"}))
            while True:
                message = json.loads(await asyncio.wait_for(socket.recv(), timeout=12))
                print(
                    "Provider event:",
                    {key: message.get(key) for key in ("code", "message", "final")},
                )
    except websockets.ConnectionClosed as exc:
        print(f"Provider closed: code={exc.code}, reason={exc.reason!r}")
    except Exception as exc:
        print(f"Probe failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
