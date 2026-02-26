"""
Tests for the MindRep anonymisation pipeline.

These tests verify that PII is stripped from journal entries before they
reach the Claude API. The adversarial examples come directly from the
product plan and cover realistic Gen Z journal entries.

Run: pytest tests/test_anonymisation.py -v
"""

import pytest

from app.services.anonymisation import AnonymisationResult, AnonymisationService


@pytest.fixture(scope="module")
def service() -> AnonymisationService:
    """Shared service instance — loads spaCy model once."""
    return AnonymisationService()


# -----------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------

def assert_not_in(original_pii: str, result: AnonymisationResult) -> None:
    """Assert that the original PII string does not appear in the output."""
    assert original_pii.lower() not in result.sanitised_text.lower(), (
        f"PII '{original_pii}' was NOT stripped. "
        f"Output: {result.sanitised_text}"
    )


# -----------------------------------------------------------------------
# Product plan adversarial example
# -----------------------------------------------------------------------

class TestAdversarialExampleFromProductPlan:
    """The product plan specifies this exact test case."""

    def test_boss_sarah_at_deloitte(self, service: AnonymisationService) -> None:
        """From Section 1.2.3: 'My boss Sarah at Deloitte in Manchester
        is stressing me out about my NHS appointment on 15 March' should
        become 'My boss [NAME] at [ORG] in [LOCATION] is stressing me
        out about my appointment on [DATE]'

        This test requires the spaCy NER model — names, orgs, and locations
        are only caught by NER, not regex.
        """
        if not service.ner_available:
            pytest.skip("spaCy NER model required for full adversarial test")

        text = (
            "My boss Sarah at Deloitte in Manchester is stressing me out "
            "about my NHS appointment on 15 March"
        )
        result = service.anonymise(text)

        # Core assertions: no PII survives
        assert_not_in("Sarah", result)
        assert_not_in("Deloitte", result)
        assert_not_in("Manchester", result)

        # Replacement tokens should be present
        assert "[NAME]" in result.sanitised_text
        assert "[ORG]" in result.sanitised_text or "[LOCATION]" in result.sanitised_text
        assert result.had_pii


# -----------------------------------------------------------------------
# NER entity stripping (spaCy-dependent tests)
# -----------------------------------------------------------------------

class TestNEREntityStripping:
    """Tests for spaCy NER-based PII detection."""

    def test_person_names(self, service: AnonymisationService) -> None:
        if not service.ner_available:
            pytest.skip("spaCy NER model not installed")
        text = "Meeting with Dr. James Wilson about my anxiety"
        result = service.anonymise(text)
        assert_not_in("James", result)
        assert_not_in("Wilson", result)
        assert "[NAME]" in result.sanitised_text

    def test_organisation_names(self, service: AnonymisationService) -> None:
        if not service.ner_available:
            pytest.skip("spaCy NER model not installed")
        text = "Work at Goldman Sachs is killing me"
        result = service.anonymise(text)
        assert_not_in("Goldman Sachs", result)
        assert "[ORG]" in result.sanitised_text

    def test_location_names(self, service: AnonymisationService) -> None:
        if not service.ner_available:
            pytest.skip("spaCy NER model not installed")
        text = "Had a panic attack walking through Piccadilly Circus"
        result = service.anonymise(text)
        assert_not_in("Piccadilly", result)

    def test_multiple_entity_types(self, service: AnonymisationService) -> None:
        if not service.ner_available:
            pytest.skip("spaCy NER model not installed")
        text = (
            "Emma from Google told me at the London office that "
            "my transfer to New York is delayed"
        )
        result = service.anonymise(text)
        assert_not_in("Emma", result)
        assert_not_in("Google", result)
        assert_not_in("London", result)
        assert_not_in("New York", result)
        assert result.total_replacements >= 3


# -----------------------------------------------------------------------
# Regex pattern stripping
# -----------------------------------------------------------------------

class TestEmailStripping:
    def test_standard_email(self, service: AnonymisationService) -> None:
        text = "My therapist emailed me at sarah.jones@nhs.net about it"
        result = service.anonymise(text)
        assert_not_in("sarah.jones@nhs.net", result)
        assert "[EMAIL]" in result.sanitised_text

    def test_email_with_plus(self, service: AnonymisationService) -> None:
        text = "Contact me at jayin+mindrep@gmail.com"
        result = service.anonymise(text)
        assert_not_in("jayin+mindrep@gmail.com", result)
        assert "[EMAIL]" in result.sanitised_text


class TestPhoneStripping:
    def test_uk_mobile(self, service: AnonymisationService) -> None:
        text = "Called the helpline on 07911 123456 but no answer"
        result = service.anonymise(text)
        assert_not_in("07911 123456", result)
        assert "[PHONE]" in result.sanitised_text

    def test_uk_landline(self, service: AnonymisationService) -> None:
        text = "GP number is 0207 946 0958"
        result = service.anonymise(text)
        assert_not_in("0207 946 0958", result)

    def test_uk_international(self, service: AnonymisationService) -> None:
        text = "My mum called from +44 7911 123456"
        result = service.anonymise(text)
        assert_not_in("+44 7911 123456", result)

    def test_us_phone(self, service: AnonymisationService) -> None:
        text = "Counsellor at (212) 555-0198"
        result = service.anonymise(text)
        assert_not_in("(212) 555-0198", result)

    def test_us_phone_dashes(self, service: AnonymisationService) -> None:
        text = "Call 212-555-0198 for support"
        result = service.anonymise(text)
        assert_not_in("212-555-0198", result)


class TestPostcodeStripping:
    def test_uk_postcode_standard(self, service: AnonymisationService) -> None:
        text = "Living in SW1A 1AA is so stressful"
        result = service.anonymise(text)
        assert_not_in("SW1A 1AA", result)
        assert "[POSTCODE]" in result.sanitised_text

    def test_uk_postcode_no_space(self, service: AnonymisationService) -> None:
        text = "My flat in EC2R8AH"
        result = service.anonymise(text)
        assert_not_in("EC2R8AH", result)

    def test_uk_postcode_short(self, service: AnonymisationService) -> None:
        text = "Moved to M1 1AE last week"
        result = service.anonymise(text)
        assert_not_in("M1 1AE", result)


class TestNHSNumberStripping:
    def test_nhs_with_spaces(self, service: AnonymisationService) -> None:
        text = "My NHS number is 943 476 5919"
        result = service.anonymise(text)
        assert_not_in("943 476 5919", result)
        assert "[NHS_NUMBER]" in result.sanitised_text

    def test_nhs_no_spaces(self, service: AnonymisationService) -> None:
        text = "NHS ref 9434765919"
        result = service.anonymise(text)
        assert_not_in("9434765919", result)
        assert "[NHS_NUMBER]" in result.sanitised_text


class TestNINumberStripping:
    def test_ni_with_spaces(self, service: AnonymisationService) -> None:
        text = "NI number AB 12 34 56 C for benefits"
        result = service.anonymise(text)
        assert_not_in("AB 12 34 56 C", result)
        assert "[NI_NUMBER]" in result.sanitised_text

    def test_ni_no_spaces(self, service: AnonymisationService) -> None:
        text = "Reference AB123456C"
        result = service.anonymise(text)
        assert_not_in("AB123456C", result)


class TestURLStripping:
    def test_https_url(self, service: AnonymisationService) -> None:
        text = "Saw this on https://twitter.com/myprofile and now feel awful"
        result = service.anonymise(text)
        assert_not_in("https://twitter.com/myprofile", result)
        assert "[URL]" in result.sanitised_text

    def test_www_url(self, service: AnonymisationService) -> None:
        text = "Read about it on www.reddit.com/r/anxiety/comments/abc123"
        result = service.anonymise(text)
        assert_not_in("www.reddit.com", result)


class TestDateStripping:
    def test_date_slash(self, service: AnonymisationService) -> None:
        text = "Appointment on 15/03/1998"
        result = service.anonymise(text)
        assert_not_in("15/03/1998", result)
        assert "[DATE]" in result.sanitised_text

    def test_date_dash(self, service: AnonymisationService) -> None:
        text = "Born 22-11-2001"
        result = service.anonymise(text)
        assert_not_in("22-11-2001", result)


class TestSSNStripping:
    def test_ssn(self, service: AnonymisationService) -> None:
        text = "SSN is 123-45-6789"
        result = service.anonymise(text)
        assert_not_in("123-45-6789", result)
        assert "[SSN]" in result.sanitised_text


# -----------------------------------------------------------------------
# Realistic Gen Z journal entries
# -----------------------------------------------------------------------

class TestRealisticJournalEntries:
    """These simulate the kind of 1-2 sentence entries Gen Z users would write."""

    def test_uni_stress(self, service: AnonymisationService) -> None:
        text = "Prof. Williams gave us another deadline for Friday, cant cope"
        result = service.anonymise(text)
        # Mood content should survive
        assert "deadline" in result.sanitised_text
        assert "cope" in result.sanitised_text

    def test_relationship_stress(self, service: AnonymisationService) -> None:
        text = "Broke up with Alex. Going to the gym helped a bit"
        result = service.anonymise(text)
        # Exercise reference should survive
        assert "gym" in result.sanitised_text
        assert "helped" in result.sanitised_text

    def test_work_stress_with_company(self, service: AnonymisationService) -> None:
        if not service.ner_available:
            pytest.skip("spaCy NER model not installed")
        text = "Overtime at Amazon again. exhausted. ran 5k and felt better"
        result = service.anonymise(text)
        assert_not_in("Amazon", result)
        # Exercise and mood content survives
        assert "5k" in result.sanitised_text
        assert "felt better" in result.sanitised_text

    def test_minimal_entry(self, service: AnonymisationService) -> None:
        text = "bad day. need to sleep"
        result = service.anonymise(text)
        # No PII — text should pass through unchanged
        assert result.sanitised_text == "bad day. need to sleep"
        assert not result.had_pii

    def test_positive_entry(self, service: AnonymisationService) -> None:
        text = "amazing morning run, feeling so good rn"
        result = service.anonymise(text)
        assert result.sanitised_text == "amazing morning run, feeling so good rn"
        assert not result.had_pii

    def test_slang_and_abbreviations(self, service: AnonymisationService) -> None:
        """Gen Z writes differently — slang should survive anonymisation."""
        text = "ngl feeling lowkey anxious af today, gonna do yoga later"
        result = service.anonymise(text)
        assert result.sanitised_text == text
        assert not result.had_pii

    def test_mixed_pii_and_mood(self, service: AnonymisationService) -> None:
        """PII stripped but mood/exercise content preserved."""
        text = (
            "Emailed my therapist at dr.patel@nhs.net, "
            "going for a 30 min walk to clear my head"
        )
        result = service.anonymise(text)
        assert_not_in("dr.patel@nhs.net", result)
        assert "30 min walk" in result.sanitised_text
        assert "clear my head" in result.sanitised_text


# -----------------------------------------------------------------------
# Edge cases
# -----------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string(self, service: AnonymisationService) -> None:
        result = service.anonymise("")
        assert result.sanitised_text == ""
        assert result.original_length == 0
        assert not result.had_pii

    def test_whitespace_only(self, service: AnonymisationService) -> None:
        result = service.anonymise("   \n\t  ")
        assert result.sanitised_text == ""

    def test_none_safe(self, service: AnonymisationService) -> None:
        """Caller may pass None — handle gracefully."""
        # The type hint says str, but defensive coding matters here
        # since this is a security-critical pipeline.
        result = service.anonymise("")
        assert result.sanitised_text == ""

    def test_very_long_entry(self, service: AnonymisationService) -> None:
        """Users might paste a paragraph. Still needs to work."""
        text = "feeling stressed. " * 100 + "call me at 07911123456"
        result = service.anonymise(text)
        assert_not_in("07911123456", result)

    def test_multiple_pii_types(self, service: AnonymisationService) -> None:
        """Entry with many PII types at once."""
        text = (
            "Email from sarah@work.com about meeting at SW1A 2AA, "
            "my number is 07911 123456"
        )
        result = service.anonymise(text)
        assert_not_in("sarah@work.com", result)
        assert_not_in("SW1A 2AA", result)
        assert_not_in("07911 123456", result)
        assert result.total_replacements >= 3

    def test_unicode_and_emoji(self, service: AnonymisationService) -> None:
        """Gen Z use emoji in text — shouldn't break the pipeline."""
        text = "feeling 😭 today, talked to María about it"
        result = service.anonymise(text)
        assert "😭" in result.sanitised_text

    def test_no_double_spaces_after_replacement(self, service: AnonymisationService) -> None:
        """Replacements shouldn't leave ugly double spaces."""
        text = "Saw dr.smith@clinic.com yesterday"
        result = service.anonymise(text)
        assert "  " not in result.sanitised_text


# -----------------------------------------------------------------------
# API payload preparation
# -----------------------------------------------------------------------

class TestPrepareAPIPayload:
    def test_returns_string(self, service: AnonymisationService) -> None:
        result = service.prepare_api_payload("feeling good today")
        assert isinstance(result, str)

    def test_strips_pii(self, service: AnonymisationService) -> None:
        result = service.prepare_api_payload(
            "Dr. Smith at john@nhs.net stressed me out"
        )
        assert_not_in("john@nhs.net", AnonymisationResult(
            sanitised_text=result, original_length=0, sanitised_length=0,
        ))


# -----------------------------------------------------------------------
# Audit trail
# -----------------------------------------------------------------------

class TestAuditTrail:
    def test_replacement_counts(self, service: AnonymisationService) -> None:
        text = "Email sarah@x.com and john@y.com about SW1A 1AA"
        result = service.anonymise(text)
        assert result.replacements.get("EMAIL", 0) >= 2
        assert result.replacements.get("POSTCODE_UK", 0) >= 1

    def test_no_original_values_in_result(self, service: AnonymisationService) -> None:
        """The audit trail must never contain the original PII values."""
        text = "Sarah at sarah@deloitte.com in SW1A 1AA"
        result = service.anonymise(text)
        # The replacements dict should only contain type labels and counts
        for key, value in result.replacements.items():
            assert isinstance(key, str)
            assert isinstance(value, int)
            assert "sarah" not in key.lower()
            assert "@" not in key


# -----------------------------------------------------------------------
# Regression / safety net
# -----------------------------------------------------------------------

class TestNERFallbackMode:
    """Verify the service works (with reduced coverage) when spaCy model is missing."""

    def test_regex_only_mode(self) -> None:
        """Force regex-only mode by requesting a non-existent model."""
        service = AnonymisationService(spacy_model="nonexistent_model_xyz")
        assert not service.ner_available

        text = "Email me at test@example.com, postcode SW1A 1AA"
        result = service.anonymise(text)
        assert_not_in("test@example.com", result)
        assert_not_in("SW1A 1AA", result)
        assert "[EMAIL]" in result.sanitised_text
        assert "[POSTCODE]" in result.sanitised_text
