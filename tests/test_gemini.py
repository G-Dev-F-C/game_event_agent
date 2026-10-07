import unittest
from unittest.mock import Mock, patch

from tools import gemini


class GeminiTimeoutTests(unittest.TestCase):
    @patch.object(gemini, "_throttle")
    @patch.object(gemini, "_get_client")
    def test_requests_bound_sdk_wait_and_disable_nested_retries(self, get_client, throttle):
        model = get_client.return_value.GenerativeModel.return_value
        model.generate_content.return_value = Mock(text='[]')
        self.assertEqual(gemini.generate_json('event'), [])
        gemini.generate_text('query')
        for call in model.generate_content.call_args_list:
            self.assertEqual(call.kwargs['request_options'], {'timeout': 60.0, 'retry': None})

    @patch.object(gemini.time, "sleep")
    @patch.object(gemini, "_throttle")
    @patch.object(gemini, "_get_client")
    def test_deadline_retries_are_bounded_including_fallback(self, get_client, throttle, sleep):
        model = get_client.return_value.GenerativeModel.return_value
        model.generate_content.side_effect = TimeoutError('504 Deadline exceeded')
        with patch.object(gemini, 'MAX_RETRIES', 3), patch.object(gemini, 'DEFAULT_MODEL', 'primary'), patch.object(gemini, 'FALLBACK_MODEL', 'fallback'):
            self.assertEqual(gemini.generate_json('event'), [])
        self.assertEqual(model.generate_content.call_count, 6)
        self.assertEqual(sleep.call_count, 4)
