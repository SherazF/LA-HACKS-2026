import asyncio
import unittest
import json
import httpx
from unittest.mock import MagicMock, AsyncMock, patch
from bus import EventBus
from model.gemma import ModelManager

class TestModelRetries(unittest.IsolatedAsyncioTestCase):
    async def test_retry_on_500(self):
        bus = EventBus()
        model_manager = ModelManager(bus)
        
        # Mock httpx.AsyncClient.post to return 500 twice, then 200
        mock_response_500 = MagicMock()
        mock_response_500.status_code = 500
        mock_response_500.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Internal Server Error", 
            request=MagicMock(), 
            response=mock_response_500
        )
        
        mock_response_200 = MagicMock()
        mock_response_200.status_code = 200
        mock_response_200.json.return_value = {
            "message": {"content": '{"response": "success"}'}
        }
        
        with patch("httpx.AsyncClient.post", side_effect=[mock_response_500, mock_response_500, mock_response_200]) as mock_post:
            # Shorten sleep for testing
            with patch("asyncio.sleep", AsyncMock()):
                result = await model_manager._query_model()
                
                self.assertEqual(mock_post.call_count, 3)
                self.assertEqual(result, {"response": "success"})

    async def test_retry_on_malformed_json(self):
        bus = EventBus()
        model_manager = ModelManager(bus)
        
        # Mock content with malformed JSON twice, then valid JSON
        mock_response_malformed = MagicMock()
        mock_response_malformed.status_code = 200
        mock_response_malformed.json.return_value = {
            "message": {"content": "not json"}
        }
        
        mock_response_valid = MagicMock()
        mock_response_valid.status_code = 200
        mock_response_valid.json.return_value = {
            "message": {"content": '{"response": "fixed"}'}
        }
        
        with patch("httpx.AsyncClient.post", side_effect=[mock_response_malformed, mock_response_valid]) as mock_post:
            with patch("asyncio.sleep", AsyncMock()):
                result = await model_manager._query_model()
                
                self.assertEqual(mock_post.call_count, 2)
                self.assertEqual(result, {"response": "fixed"})

if __name__ == "__main__":
    unittest.main()
