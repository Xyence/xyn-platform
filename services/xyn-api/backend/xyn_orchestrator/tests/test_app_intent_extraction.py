from django.test import SimpleTestCase

from xyn_orchestrator import xyn_api


class AppIntentExtractionTests(SimpleTestCase):
    def test_extracts_named_title_and_domain_entities(self):
        prompt = (
            'Build an application named “Real Estate Deal Finder”. '
            "Users create campaigns, monitor properties, review signals, and manage sources."
        )

        fields = xyn_api._extract_app_intent_fields(prompt)

        self.assertEqual(fields.get("title"), "Real Estate Deal Finder")
        entities = set(fields.get("requested_entities") or [])
        self.assertIn("campaigns", entities)
        self.assertIn("properties", entities)
        self.assertIn("signals", entities)
        self.assertIn("sources", entities)
        self.assertNotIn("racks", entities)

    def test_does_not_match_rack_from_tracking(self):
        fields = xyn_api._extract_app_intent_fields(
            "Track artifact persistence and raw artifact tracking for compliance."
        )
        self.assertNotIn("racks", set(fields.get("requested_entities") or []))
