from django.test import TestCase

from xyn_orchestrator.jurisdiction import (
    is_canonical_jurisdiction,
    require_canonical_jurisdiction,
)


class JurisdictionValidationTests(TestCase):
    def test_canonical_jurisdictions_pass(self):
        self.assertTrue(is_canonical_jurisdiction("mo-stl-city"))
        self.assertTrue(is_canonical_jurisdiction("mo-stl-county"))
        self.assertTrue(is_canonical_jurisdiction("tx-travis-county"))

    def test_invalid_jurisdictions_fail(self):
        self.assertFalse(is_canonical_jurisdiction("tx"))
        self.assertFalse(is_canonical_jurisdiction("stl"))
        self.assertFalse(is_canonical_jurisdiction("mo-stl"))
        with self.assertRaises(ValueError):
            require_canonical_jurisdiction("tx", context="jurisdiction")

    def test_empty_jurisdiction_is_allowed(self):
        self.assertEqual(require_canonical_jurisdiction("", context="jurisdiction"), "")
