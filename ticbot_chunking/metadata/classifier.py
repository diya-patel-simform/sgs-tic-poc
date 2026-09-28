"""Rule-based document-level metadata extraction, plus an optional LLM
classifier fallback for fields rules can't decide (business area / topic).

Per section 7: "Rules: folder and file name, patterns on the first page
(certificate no., validity, 'Last Amended on'), and fixed page headers.
LLM classifier: business area and topic, where the rules don't decide.
Pattern extraction: standard and method codes such as IS / ISO / AOAC /
FDA BAM / APHA / SO-IN-… codes."
"""
from __future__ import annotations

import re

CERTIFICATE_NO_RE = re.compile(r"\b(?:Certificate\s*(?:No\.?|Number)?\s*[:\-]?\s*)(TC[-\s]?\d+)\b", re.IGNORECASE)
VALIDITY_RE = re.compile(
    r"\bValid(?:ity)?\s*(?:from)?\s*[:\-]?\s*"
    r"(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\.\d{1,2}\.\d{4})\s*(?:to|-|–)\s*"
    r"(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\.\d{1,2}\.\d{4})",
    re.IGNORECASE,
)
LAST_AMENDED_RE = re.compile(
    r"Last\s+Amended\s+on\s*[:\-]?\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})", re.IGNORECASE
)
ACCREDITATION_STANDARD_RE = re.compile(r"\bISO/?\s*IEC\s*17025\s*[:\-]?\s*(\d{4})\b", re.IGNORECASE)
LAB_LOCATION_RE = re.compile(r"Laboratory\s+Name\s*:?\s*([^\n]+)", re.IGNORECASE)

# A generic Commonwealth/Indian statutory-drafting convention: a
# regulation/act/rules almost always names itself in a "short title"
# clause of exactly this shape ("These regulations may be called the
# X Regulations, 2011."). When present, this is a far more reliable
# document-title signal than any heading/letterhead heuristic — it's the
# document's own, self-declared real name — and it's a document-type
# convention, not specific to any one regulation.
STATUTORY_TITLE_RE = re.compile(
    r"\b(?:This|These)\s+(?:regulations?|rules?|act|order)\s+may\s+be\s+called\s+(?:the\s+)?"
    r"([A-Z][^.]*?)\s*\.",
    re.IGNORECASE | re.DOTALL,
)


def extract_statutory_title(text: str) -> str | None:
    m = STATUTORY_TITLE_RE.search(text)
    if not m:
        return None
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    return title or None

# Standard / method code families referenced by NABL scope "Method" columns
# and regulation citations.
METHOD_CODE_RE = re.compile(
    r"\b("
    r"IS\s?\d{2,6}(?:\s*[:\-]\s*\d{4})?"
    r"|ISO\s?\d{2,6}(?:[-/]\d+)?(?:\s*[:\-]\s*\d{4})?"
    r"|AOAC\s?\d{3,6}(?:\.\d+)?"
    r"|FDA\s?BAM(?:\s*Chapter\s*\d+)?"
    r"|APHA\s?(?:\d+(?:th|st|nd|rd)\s*Edn)?(?:\s*Chapter\s*\d+)?"
    r"|SO-IN-[A-Za-z0-9\-]+"
    r")\b",
    re.IGNORECASE,
)


def extract_certificate_no(text: str) -> str | None:
    m = CERTIFICATE_NO_RE.search(text)
    return m.group(1).upper().replace(" ", "-") if m else None


def extract_validity(text: str) -> str | None:
    m = VALIDITY_RE.search(text)
    return f"{m.group(1)} to {m.group(2)}" if m else None


def extract_last_amended(text: str) -> str | None:
    m = LAST_AMENDED_RE.search(text)
    return m.group(1) if m else None


def extract_accreditation_standard(text: str) -> str | None:
    m = ACCREDITATION_STANDARD_RE.search(text)
    return f"ISO/IEC 17025: {m.group(1)}" if m else None


def extract_lab_location(text: str) -> str | None:
    """The accredited lab's name/address, from a real NABL scope document's
    "Laboratory Name : <name>, <address>" line (e.g. page 1 of the scope
    annexure)."""
    m = LAB_LOCATION_RE.search(text)
    return m.group(1).strip() if m else None


def extract_method_codes(text: str) -> list[str]:
    seen: list[str] = []
    for m in METHOD_CODE_RE.finditer(text):
        code = re.sub(r"\s+", " ", m.group(1).strip())
        if code not in seen:
            seen.append(code)
    return seen


DOC_TYPE_FILENAME_HINTS: dict[str, str] = {
    "regulation": "regulation",
    "contaminant": "regulation",
    "fssai": "regulation",
    "scope": "accreditation_scope",
    "accreditation": "accreditation_scope",
    "nabl": "accreditation_scope",
    "catalog": "brochure",
    "catalogue": "brochure",
    "brochure": "brochure",
    "molecular": "brochure",
    "capability": "capability_matrix",
    "contact": "contact_directory",
    "reference": "reference_register",
    "licensed": "reference_register",
}


def guess_doc_type_from_filename(filename: str) -> str | None:
    lower = filename.lower()
    for hint, doc_type in DOC_TYPE_FILENAME_HINTS.items():
        if hint in lower:
            return doc_type
    return None


# Matches this project's own multi-page-excerpt sample filename convention,
# e.g. "SGS_Molecular_Catalog_pages_3-4-12.pdf" (a 3-page excerpt of the
# original catalog's pages 3, 4 and 12) or
# "SGS_Health_Nutrition_pages_2-5-6-9-10.pdf" — a generic, filename-driven
# fallback for a chunk's printed page label (Task 3.9), used only when
# nothing else (a parsed printed-page-number paragraph — see
# `parsers.ir.ROLE_PAGE_NUMBER` — takes priority where available) supplies
# one directly.
_PAGES_SUFFIX_RE = re.compile(r"_pages_(\d+(?:-\d+)*)$", re.IGNORECASE)


def infer_printed_page_labels(filename: str, physical_page_numbers: list[int]) -> dict[int, str] | None:
    """Parses a `..._pages_<n>(-<n>)*` filename suffix into
    {physical_page_number: original_page_label}, in the order encoded by
    the filename. Returns None — never a guess — when the filename doesn't
    match this convention, or when the number of pages the filename
    encodes doesn't match `len(physical_page_numbers)` (e.g. a plain
    contiguous "pages_1-5" range suffix on a genuinely 5-page file is
    ambiguous between "a 2-page excerpt of original pages 1 and 5" and "a
    5-page contiguous range" — safer to decline than guess which)."""
    stem = re.sub(r"\.[^.]+$", "", filename)
    m = _PAGES_SUFFIX_RE.search(stem)
    if not m:
        return None
    original_pages = m.group(1).split("-")
    if len(original_pages) != len(physical_page_numbers):
        return None
    return dict(zip(physical_page_numbers, original_pages))


def classify_business_area_llm(text: str, candidate_areas: list[str]) -> str | None:
    """Optional LLM fallback for business area / topic classification when
    filename and first-page rules don't decide. Requires
    AZURE_OPENAI_CHAT_DEPLOYMENT to be configured; returns None otherwise so
    callers can fall back to 'unclassified' rather than fail the pipeline.
    """
    from ticbot_chunking.config import OPENAI

    if not OPENAI.is_configured or not OPENAI.chat_deployment:
        return None

    from openai import AzureOpenAI

    client = AzureOpenAI(
        azure_endpoint=OPENAI.endpoint,
        api_key=OPENAI.api_key,
        api_version=OPENAI.api_version,
    )
    prompt = (
        "Classify the business area of this document excerpt into exactly one of: "
        f"{', '.join(candidate_areas)}. Respond with only the label.\n\n{text[:2000]}"
    )
    resp = client.chat.completions.create(
        model=OPENAI.chat_deployment,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=10,
    )
    label = (resp.choices[0].message.content or "").strip()
    return label if label in candidate_areas else None
