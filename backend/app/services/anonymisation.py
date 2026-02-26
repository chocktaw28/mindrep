"""
MindRep Anonymisation Service
=============================
Strips all PII from mood journal entries BEFORE they reach the Claude API.

This is a GDPR compliance requirement — mood journal text is special category
health data under UK GDPR Article 9. The Claude API must never receive any
information that could identify a user.

Pipeline:
    Raw text → spaCy NER (names, orgs, locations, dates)
              → Regex (emails, phones, postcodes, NHS/NI numbers, URLs, DOBs)
              → Sanitised text (no metadata, no user ID, nothing)

Performance: <10ms per entry (spaCy NER ~5ms for 20-50 tokens, regex <1ms).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import ClassVar

import spacy
from spacy.language import Language

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class AnonymisationResult:
    """Holds the sanitised text and an audit log of what was stripped.

    The audit log records replacement types and counts — never the original
    PII values — so we can verify the pipeline is working without creating
    a secondary data leak.
    """
    sanitised_text: str
    original_length: int
    sanitised_length: int
    replacements: dict[str, int] = field(default_factory=dict)

    @property
    def had_pii(self) -> bool:
        return sum(self.replacements.values()) > 0

    @property
    def total_replacements(self) -> int:
        return sum(self.replacements.values())


# ---------------------------------------------------------------------------
# Regex patterns for UK/US PII
# ---------------------------------------------------------------------------

# Why these specific patterns: the product plan specifies UK-first launch
# with US university expansion. We cover the PII formats most likely to
# appear in a Gen Z student's 1-2 sentence mood journal entry.

_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    # Email addresses
    (
        "EMAIL",
        re.compile(
            r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
        ),
        "[EMAIL]",
    ),
    # Social Security Numbers (US): xxx-xx-xxxx
    # Must come before phone patterns to avoid partial matches.
    (
        "SSN",
        re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "[SSN]",
    ),
    # UK National Insurance numbers: AB 12 34 56 C
    # Must come before phone patterns.
    (
        "NI_NUMBER",
        re.compile(
            r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b",
            re.IGNORECASE,
        ),
        "[NI_NUMBER]",
    ),
    # NHS numbers: 10 digits, often written with spaces (e.g. 943 476 5919).
    # Must come BEFORE US phone patterns — both match 10-digit sequences,
    # but NHS numbers use 3-3-4 grouping and UK is our primary market.
    (
        "NHS_NUMBER",
        re.compile(r"\b\d{3}\s\d{3}\s\d{4}\b"),
        "[NHS_NUMBER]",
    ),
    # NHS numbers without spaces (just 10 contiguous digits).
    # Placed separately so spaced version matches first.
    (
        "NHS_NUMBER_NOSPACE",
        re.compile(r"\b\d{10}\b"),
        "[NHS_NUMBER]",
    ),
    # UK phone numbers: +44, 07xxx, 01xxx, 02xxx, 0800 etc.
    (
        "PHONE_UK",
        re.compile(
            r"(?<!\d)"  # no digit before
            r"(?:"
            r"\+44\s?\(?\d\)?\s?\d[\d\s\-]{7,10}"  # +44 variants
            r"|0[1-9][\d\s\-]{8,12}"                # 0xxx local
            r")"
            r"(?!\d)"  # no digit after
        ),
        "[PHONE]",
    ),
    # US phone numbers: (xxx) xxx-xxxx, xxx-xxx-xxxx, +1 etc.
    (
        "PHONE_US",
        re.compile(
            r"(?<!\d)"
            r"(?:"
            r"\+?1[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}"
            r"|\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}"
            r")"
            r"(?!\d)"
        ),
        "[PHONE]",
    ),
    # UK postcodes: SW1A 1AA, EC2R 8AH, M1 1AE, etc.
    (
        "POSTCODE_UK",
        re.compile(
            r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b",
            re.IGNORECASE,
        ),
        "[POSTCODE]",
    ),
    # US zip codes: 5-digit or 5+4 format
    (
        "ZIP_US",
        re.compile(r"\b\d{5}(?:-\d{4})?\b"),
        "[ZIPCODE]",
    ),
    # URLs with identifying paths (catch broadly — journals shouldn't have URLs)
    (
        "URL",
        re.compile(
            r"https?://[^\s,;\"'<>)}\]]{3,}"
            r"|www\.[^\s,;\"'<>)}\]]{3,}"
        ),
        "[URL]",
    ),
    # Dates in common formats: 15/03/1998, 15-03-1998, March 15 1998, 15 Mar 98
    # Deliberately broad — a journal entry referencing specific dates could
    # enable re-identification when combined with other context.
    (
        "DATE_NUMERIC",
        re.compile(
            r"\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b"
        ),
        "[DATE]",
    ),
]


# ---------------------------------------------------------------------------
# The anonymisation service
# ---------------------------------------------------------------------------

class AnonymisationService:
    """Strips PII from journal text before it's sent to the Claude API.

    Usage:
        service = AnonymisationService()
        result = service.anonymise("My boss Sarah at Deloitte is stressing me out")
        # result.sanitised_text → "My boss [NAME] at [ORG] is stressing me out"

    The service is designed to be instantiated once at app startup and reused —
    the spaCy model is loaded once and kept in memory (~15MB).
    """

    # Mapping from spaCy entity labels to our replacement tokens.
    # We consolidate granular spaCy labels into broad categories to avoid
    # leaking entity-type information that could aid re-identification.
    _NER_LABEL_MAP: ClassVar[dict[str, str]] = {
        "PERSON": "[NAME]",
        "ORG": "[ORG]",
        "GPE": "[LOCATION]",      # geopolitical entities (cities, countries)
        "LOC": "[LOCATION]",      # non-GPE locations (mountains, rivers)
        "FAC": "[LOCATION]",      # facilities (buildings, airports)
        "DATE": "[DATE]",
        "TIME": "[TIME]",
        "NORP": "[GROUP]",        # nationalities, religious/political groups
    }

    def __init__(self, spacy_model: str = "en_core_web_sm") -> None:
        self._nlp: Language | None = None
        self._model_name = spacy_model

        try:
            self._nlp = spacy.load(spacy_model, disable=["parser", "lemmatizer"])
            logger.info("Anonymisation: spaCy model '%s' loaded", spacy_model)
        except OSError:
            # Model not installed — fall back to regex-only mode.
            # This is acceptable for dev/testing but spaCy NER MUST be
            # available in production. Log a loud warning.
            logger.warning(
                "Anonymisation: spaCy model '%s' not found. "
                "Running in REGEX-ONLY mode. NER-based entity detection "
                "is DISABLED. Install the model before processing real "
                "user data: python -m spacy download %s",
                spacy_model,
                spacy_model,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def anonymise(self, text: str) -> AnonymisationResult:
        """Full anonymisation pipeline. Call this before any Claude API request.

        Returns an AnonymisationResult with the sanitised text and an audit
        trail of what was stripped (types and counts, never original values).
        """
        if not text or not text.strip():
            return AnonymisationResult(
                sanitised_text="",
                original_length=0,
                sanitised_length=0,
            )

        replacements: dict[str, int] = {}
        working_text = text

        # Step 1 — Regex FIRST: replace structured PII (emails, phones,
        # NHS/NI numbers, postcodes, numeric dates) before spaCy NER runs.
        # This prevents NER from mis-tagging e.g. "07911 123456" as DATE,
        # or "user@gmail.com" as ORG, which would block the correct label.
        working_text = self._strip_regex_patterns(working_text, replacements)

        # Step 2 — spaCy NER: catch names, orgs, locations, and narrative
        # dates ("15 March", "next Monday") that regex cannot handle.
        working_text = self._strip_ner_entities(working_text, replacements)

        # Step 3 — Normalise whitespace (replacements can leave double spaces)
        working_text = re.sub(r"  +", " ", working_text).strip()

        result = AnonymisationResult(
            sanitised_text=working_text,
            original_length=len(text),
            sanitised_length=len(working_text),
            replacements=replacements,
        )

        if result.had_pii:
            logger.info(
                "Anonymisation stripped %d PII element(s): %s",
                result.total_replacements,
                {k: v for k, v in result.replacements.items()},
            )

        return result

    def prepare_api_payload(self, text: str) -> str:
        """Convenience method: returns just the sanitised text string,
        ready to embed in a Claude API request body.

        This is the method the mood_classifier service should call.
        """
        return self.anonymise(text).sanitised_text

    @property
    def ner_available(self) -> bool:
        """Whether the spaCy NER model is loaded. Must be True in production."""
        return self._nlp is not None

    # ------------------------------------------------------------------
    # Step 1: spaCy NER entity stripping
    # ------------------------------------------------------------------

    def _strip_ner_entities(
        self, text: str, replacements: dict[str, int]
    ) -> str:
        """Replace named entities detected by spaCy with generic tokens.

        Also supplements NER with a PROPN scan to catch names that the
        small model misses (e.g. single-word first names without titles).

        Processes all spans in reverse char order so that offsets remain
        valid as replacements are applied.
        """
        if self._nlp is None:
            return text

        doc = self._nlp(text)

        # Collect (start_char, end_char, replacement_token, label_key) spans.
        spans: list[tuple[int, int, str, str]] = []

        # Track which token indices are already covered by a NER entity so
        # the PROPN fallback doesn't double-process them.
        ner_token_indices: set[int] = set()

        for ent in doc.ents:
            replacement_token = self._NER_LABEL_MAP.get(ent.label_)
            if replacement_token is None:
                # Entity type we don't replace (MONEY, CARDINAL, etc.).
                continue

            # Skip entities that sit inside a regex placeholder (e.g. the
            # token "SSN" inside "[SSN]" or "EMAIL" inside "[EMAIL]").
            # After the regex step, placeholders like "[SSN]" are in the text;
            # spaCy may re-tag the inner word as an entity and double-replace.
            if ent.start_char > 0 and text[ent.start_char - 1] == "[":
                continue

            # For DATE and TIME: only replace if the entity text contains at
            # least one digit.  This prevents vague temporal words like
            # "morning", "today", "tonight" from being stripped — they carry
            # mood context and cannot re-identify anyone on their own.
            # Entities like "15 March" or "3pm" contain digits and ARE replaced.
            if ent.label_ in ("DATE", "TIME") and not any(
                c.isdigit() for c in ent.text
            ):
                continue

            spans.append((ent.start_char, ent.end_char, replacement_token, ent.label_))
            for tok in ent:
                ner_token_indices.add(tok.i)

        # Supplement: catch PROPN tokens not already covered by a NER entity.
        # en_core_web_sm sometimes misses single first-names ("Emma", "Alex")
        # that appear without a title or surname.  Any capitalised alphabetic
        # proper noun that wasn't caught by NER is a likely name.
        # Guard: skip tokens that are already inside a regex placeholder
        # (e.g. the word "EMAIL" inside "[EMAIL]").
        for tok in doc:
            if (
                tok.pos_ == "PROPN"
                and tok.i not in ner_token_indices
                and tok.text[0].isupper()
                and tok.text.isalpha()
                and not (tok.idx > 0 and text[tok.idx - 1] == "[")
            ):
                spans.append((tok.idx, tok.idx + len(tok.text), "[NAME]", "PERSON"))

        # Apply replacements right-to-left so earlier offsets stay valid.
        spans.sort(key=lambda s: s[0], reverse=True)
        for start, end, replacement_token, label_key in spans:
            text = text[:start] + replacement_token + text[end:]
            replacements[label_key] = replacements.get(label_key, 0) + 1

        return text

    # ------------------------------------------------------------------
    # Step 2: Regex pattern stripping
    # ------------------------------------------------------------------

    def _strip_regex_patterns(
        self, text: str, replacements: dict[str, int]
    ) -> str:
        """Apply regex patterns for structured PII that NER might miss.

        Patterns are applied in order — earlier patterns take priority
        (e.g. SSN is checked before generic digit sequences).
        """
        for label, pattern, token in _PATTERNS:
            matches = pattern.findall(text)
            if matches:
                text = pattern.sub(token, text)
                replacements[label] = replacements.get(label, 0) + len(matches)

        return text


# ---------------------------------------------------------------------------
# Module-level singleton for convenience
# ---------------------------------------------------------------------------

_default_service: AnonymisationService | None = None


def get_anonymisation_service() -> AnonymisationService:
    """Returns a module-level singleton. Use this in FastAPI dependency injection."""
    global _default_service
    if _default_service is None:
        _default_service = AnonymisationService()
    return _default_service
