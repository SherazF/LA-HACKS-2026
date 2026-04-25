import asyncio
import logging
import os

import aioconsole
from bus import EventBus

logger = logging.getLogger(__name__)

class ChatManager:
    def __init__(self, bus: EventBus):
        self.bus = bus
        self.bus.subscribe("vision_result", self.on_vision_result)
        self.bus.subscribe("chat_response", self.on_chat_response)

    async def on_vision_result(self, text):
        await aioconsole.aprint(f"\n[Gemma Vision]: {text}\n> ", end="")

    async def on_chat_response(self, text):
        await aioconsole.aprint(f"\n[Gemma Chat]: {text}\n> ", end="")

    async def start(self):
        if os.getenv("ENABLE_CONSOLE_CHAT", "0").lower() not in ("1", "true", "yes"):
            return
        await aioconsole.aprint("Chat Manager started. Type your message and press Enter. (Type 'quit' to exit)")
        while True:
            try:
                line = await aioconsole.ainput("> ")
                if line.strip():
                    user_text = line.strip()
                    if user_text.lower() in ['exit', 'quit', 'q']:
                        await self.bus.emit("quit")
                        break
                    await self.bus.emit("chat_input", text=user_text)
            except EOFError:
                await self.bus.emit("quit")
                break
            except Exception as e:
                logger.error(f"Chat input error: {e}")
                await asyncio.sleep(0.1)
