import unittest

import bubbles


class BubblesCalendarParsingTests(unittest.TestCase):
    def test_generic_schedule_intent_starts_empty_draft(self):
        request = bubbles.extract_event_request("can you schedule a new appointment?")
        self.assertIsNotNone(request)
        self.assertEqual(request["title"], "")
        self.assertIsNone(request["date"])
        self.assertIsNone(request["time"])

    def test_event_request_extracts_title_date_and_time(self):
        request = bubbles.extract_event_request("Schedule dentist on April 25 at 2:30pm")
        self.assertEqual(request["title"], "Dentist")
        self.assertEqual(request["date"], "2026-04-25")
        self.assertEqual(request["time"], "14:30")

    def test_day_month_phrase_uses_next_matching_date(self):
        self.assertEqual(bubbles.parse_human_date("25th of April"), "2026-04-25")

    def test_next_weekday_phrase_is_supported(self):
        self.assertEqual(bubbles.parse_human_date("next Friday"), "2026-04-24")

    def test_calendar_range_detection(self):
        self.assertTrue(bubbles.asks_for_calendar_range("show my appointments for seven days"))
        self.assertEqual(bubbles.parse_days_from_text("show my appointments for seven days"), 7)

    def test_chat_prompt_includes_persona_and_memory(self):
        bubbles.CHAT_MEMORY[123] = [{"role": "user", "content": "remember this"}]
        prompt = bubbles.format_chat_prompt(123, "hello")
        self.assertIn("You are Bubbles", prompt)
        self.assertIn("User: remember this", prompt)
        self.assertIn("User: hello", prompt)


if __name__ == "__main__":
    unittest.main()
