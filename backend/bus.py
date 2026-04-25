import asyncio
import logging
import inspect
from typing import Callable, Any, Dict, List

logger = logging.getLogger(__name__)

class EventBus:
    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_name: str, handler: Callable):
        if event_name not in self._handlers:
            self._handlers[event_name] = []
        self._handlers[event_name].append(handler)
        logger.debug(f"Subscribed to {event_name}: {handler.__name__ if hasattr(handler, '__name__') else handler}")

    async def emit(self, event_name: str, **kwargs):
        if event_name not in self._handlers:
            return

        tasks = []
        for handler in self._handlers[event_name]:
            if inspect.iscoroutinefunction(handler):
                tasks.append(handler(**kwargs))
            else:
                # Wrap sync handler in a task
                loop = asyncio.get_running_loop()
                tasks.append(loop.run_in_executor(None, lambda h=handler, kw=kwargs: h(**kw)))

        if tasks:
            await asyncio.gather(*tasks)
