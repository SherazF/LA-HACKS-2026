import cv2
import asyncio
import logging
import numpy as np
from bus import EventBus

logger = logging.getLogger(__name__)

class UIManager:
    def __init__(self, bus: EventBus):
        self.bus = bus
        self.latest_guidance = "Starting up..."
        self.latest_chat = ""
        self.current_frame = None
        
        self.bus.subscribe("vision_result", self.on_vision_result)
        self.bus.subscribe("chat_response", self.on_chat_response)

    def on_frame(self, frame):
        self.current_frame = frame.copy()

    def on_vision_result(self, text):
        self.latest_guidance = text
        logger.info(f"UI received guidance update")

    def on_chat_response(self, text):
        self.latest_chat = text
        logger.info(f"UI received chat update")

    def wrap_text(self, text, font, font_scale, max_width):
        """Wraps text to fit within a maximum width."""
        words = text.split(' ')
        lines = []
        current_line = []
        
        for word in words:
            test_line = ' '.join(current_line + [word])
            (w, h), _ = cv2.getTextSize(test_line, font, font_scale, 1)
            if w <= max_width:
                current_line.append(word)
            else:
                lines.append(' '.join(current_line))
                current_line = [word]
        
        if current_line:
            lines.append(' '.join(current_line))
        return lines

    async def start(self):
        logger.info("UI Manager started")
        cv2.namedWindow("PC Build Guidance", cv2.WINDOW_NORMAL)
        
        while True:
            if self.current_frame is not None:
                display_frame = self.current_frame.copy()
                h, w, _ = display_frame.shape
                
                # Setup fonts
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.6
                thickness = 1
                max_width = w - 40
                
                # Draw semi-transparent background boxes for readability
                overlay = display_frame.copy()
                # Top box for guidance
                cv2.rectangle(overlay, (0, 0), (w, 150), (0, 0, 0), -1)
                # Bottom box for chat
                cv2.rectangle(overlay, (0, h - 80), (w, h), (0, 0, 0), -1)
                cv2.addWeighted(overlay, 0.5, display_frame, 0.5, 0, display_frame)

                # Wrap and draw Guidance (Green)
                guidance_lines = []
                for paragraph in self.latest_guidance.split('\n'):
                    if paragraph.strip():
                        guidance_lines.extend(self.wrap_text(paragraph, font, font_scale, max_width))
                
                y0, dy = 30, 25
                for i, line in enumerate(guidance_lines[:5]): # Show up to 5 lines
                    cv2.putText(display_frame, line, (20, y0 + i*dy), 
                                font, font_scale, (0, 255, 0), thickness)
                
                # Wrap and draw Chat (Cyan/Yellow)
                if self.latest_chat:
                    chat_lines = self.wrap_text(f"Gemma: {self.latest_chat}", font, 0.5, max_width)
                    for i, line in enumerate(chat_lines[-2:]): # Show last 2 lines
                        cv2.putText(display_frame, line, (20, h - 50 + i*20), 
                                    font, 0.5, (255, 255, 0), thickness)

                cv2.imshow("PC Build Guidance", display_frame)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                logger.info("Quitting...")
                break
                
            await asyncio.sleep(0.03) # ~30 FPS UI update

        cv2.destroyAllWindows()
        await self.bus.emit("quit")
