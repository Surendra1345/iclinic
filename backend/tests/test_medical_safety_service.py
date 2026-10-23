import unittest

from src.services.medical_safety_service import is_emergency_report


class EmergencyDetectionTests(unittest.TestCase):
    def test_current_emergency_reports_are_detected(self):
        for message in (
            "I have chest pain",
            "I'm having difficulty breathing right now",
            "I think I'm having a heart attack",
            "No shortness of breath, but I have chest pain now",
            "I can't breathe",
            "I am short of breath",
            "I feel faint",
            "I had chest pain last week but I have it again today",
            "I had chest pain last week but I have it now",
            "I don't have chest pain, but now my chest hurts",
            "My doctor asked if I have chest pain, and I do",
            "I'm not sure if I have chest pain",
        ):
            with self.subTest(message=message):
                self.assertTrue(is_emergency_report(message))

    def test_denied_symptoms_and_emergency_are_not_detected(self):
        for message in (
            "I don't have chest pain",
            "No shortness of breath",
            "I do not have difficulty breathing",
            "I don't think this is an emergency",
            "I am not having a heart attack",
        ):
            with self.subTest(message=message):
                self.assertFalse(is_emergency_report(message))

    def test_historical_reports_are_not_detected(self):
        for message in (
            "I had chest pain last week",
            "I had a stroke 2 years ago",
            "I have a history of heart attack",
            "I fainted yesterday",
            "I'm not sure whether I had chest pain last week",
        ):
            with self.subTest(message=message):
                self.assertFalse(is_emergency_report(message))

    def test_informational_questions_are_not_detected(self):
        for message in (
            "What causes chest pain?",
            "What is a heart attack?",
            "Could shortness of breath indicate an emergency?",
            "How can choking happen?",
            "Is chest pain always an emergency?",
            "My doctor asked if I have chest pain",
        ):
            with self.subTest(message=message):
                self.assertFalse(is_emergency_report(message))


if __name__ == "__main__":
    unittest.main()
