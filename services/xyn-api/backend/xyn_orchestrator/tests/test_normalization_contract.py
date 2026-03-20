from django.test import SimpleTestCase

from xyn_orchestrator.matching.normalization import (
    normalize_address_record,
    normalize_owner_name,
    normalize_parcel_id,
    register_address_adapter,
    register_parcel_adapter,
)


class NormalizationContractTests(SimpleTestCase):
    def test_address_normalization_basic(self):
        row = normalize_address_record("123 North Main Street")
        self.assertEqual(row["normalized"], "123 n main st")
        self.assertEqual(row["components"]["house_number"], "123")
        self.assertEqual(row["components"]["predirectional"], "n")
        self.assertEqual(row["components"]["street_suffix"], "st")
        self.assertEqual(row["quality"], "ok")

    def test_address_unit_normalization(self):
        row = normalize_address_record("55 West Elm Rd Apt 3B")
        self.assertIn("unit 3b", row["normalized"])
        self.assertEqual(row["components"]["unit"], "3b")

    def test_address_partial_when_missing_house_number(self):
        row = normalize_address_record("Main Street")
        self.assertEqual(row["quality"], "partial")

    def test_owner_entity_normalization(self):
        row = normalize_owner_name("Acme Holdings LLC")
        self.assertEqual(row["kind"], "entity")
        self.assertEqual(row["normalized"], "acme holdings")

    def test_owner_comma_name_normalization(self):
        row = normalize_owner_name("Smith, Jane")
        self.assertEqual(row["kind"], "person")
        self.assertEqual(row["normalized"], "jane smith")

    def test_parcel_normalization(self):
        row = normalize_parcel_id("12-34-56.789")
        self.assertEqual(row["normalized"], "123456789")
        self.assertEqual(row["alternate_forms"], ["12-34-56-789"])

    def test_jurisdiction_adapter_fallback(self):
        row = normalize_address_record("100 Main St", jurisdiction="tx-travis-county")
        self.assertEqual(row["normalized"], "100 main st")

    def test_jurisdiction_adapter_override(self):
        def _adapter(raw: str):
            return {
                "raw": raw,
                "normalized": "custom",
                "components": {},
                "quality": "ok",
                "format": "jurisdiction_specific",
            }

        register_address_adapter("tx-travis-county", _adapter)
        row = normalize_address_record("100 Main St", jurisdiction="tx-travis-county")
        self.assertEqual(row["normalized"], "custom")

        def _parcel_adapter(raw: str):
            return {
                "raw": raw,
                "normalized": "parcel-custom",
                "alternate_forms": [],
                "format": "jurisdiction_specific",
            }

        register_parcel_adapter("tx-travis-county", _parcel_adapter)
        parcel_row = normalize_parcel_id("12-34-56", jurisdiction="tx-travis-county")
        self.assertEqual(parcel_row["normalized"], "parcel-custom")
