# Ambiguous PDF Unicode Repair Design

## Problem

Some embedded PDF fonts use character identifiers (CIDs) that render correctly but are absent from the font's `/ToUnicode` CMap. Accessibility checkers then report that characters cannot be mapped to Unicode, and assistive technology cannot reliably read, search, or copy them.

The example document uses CID `2870` as a superscript digit, but the design must work across PDFs and must not hard-code that font, CID, page, or character.

## Goals

- Detect used CIDs that lack Unicode mappings.
- Resolve mappings deterministically whenever the PDF or embedded font supplies authoritative evidence.
- Call DeepSeek V4 Pro only for genuinely ambiguous mappings.
- Give DeepSeek enough visual, textual, typographic, and candidate context to make a defensible decision.
- Modify the PDF only when the decision passes strict confidence and consistency gates.
- Preserve visual rendering and every existing Unicode mapping.
- Report repaired and unresolved characters with an audit trail.

## Non-goals

- Reconstruct complete mathematical semantics such as MathML.
- Guess mappings from an LLM response that is uncertain or internally inconsistent.
- OCR or rebuild pages that already contain extractable text.
- Replace correct `/ToUnicode` entries.

## Pipeline Placement

Add a Unicode-map repair stage after the source PDF is copied to the remediation output and before structure rebuilding and final validation. This stage operates on the output copy only.

The full `PDFRemediator.fix_all()` path always invokes the stage. A document with no missing used CIDs exits without making an API call or changing the PDF.

## Stage 1: Inventory Used CIDs

For every page and font resource:

1. Parse text-showing operators (`Tj`, `TJ`, `'`, and `"`).
2. Track the active font selected by `Tf`, including fonts inside Form XObjects.
3. Decode character codes using the font's encoding and code-space ranges.
4. Parse the current `/ToUnicode` CMap.
5. Record each used code that has no valid Unicode destination, along with its font object and every occurrence.

The detector deduplicates by font object plus character code because one font-level mapping applies to all occurrences.

## Stage 2: Deterministic Resolution

Before contacting DeepSeek, generate candidates from authoritative font evidence:

- the embedded font's Unicode `cmap` tables;
- meaningful PostScript glyph names;
- Type 1 encoding and Differences arrays;
- CID-to-GID mappings combined with OpenType substitution information;
- an existing equivalent glyph in the same embedded font;
- consistent mappings for the same embedded font program elsewhere in the document.

If these sources yield exactly one non-conflicting Unicode sequence, add it without an LLM call. If they conflict or yield no unique answer, classify the code as ambiguous.

Visual similarity alone is not authoritative and cannot bypass the ambiguity path.

## Stage 3: DeepSeek V4 Pro Context Package

For each ambiguous font/code pair, send one request to `deepseek-v4-pro` at the configured DeepSeek API endpoint. The request contains:

### Images

- An isolated high-resolution rendering of the target glyph on a plain background.
- Up to three representative line crops from distinct occurrences.
- Each line crop includes enough neighboring content to establish meaning and marks the target with an external outline that does not cover the glyph.
- When available, a comparison strip containing visually related, already-mapped glyphs from the same font with their Unicode labels outside the glyph area.

### Textual evidence

- Document title, page number, and nearby heading.
- The containing line and paragraph with the target replaced by `[UNKNOWN]`.
- Reliable text immediately before and after the target.
- Font subtype, encoding, CID, GID, glyph name, font size, baseline offset, writing direction, and whether its geometry indicates superscript or subscript placement.
- The deterministic candidate set, evidence for each candidate, and any conflicts.
- Known mappings for neighboring or related glyphs in the same font.
- Whether all sampled occurrences appear semantically compatible.

PDF-derived text is delimited as untrusted document data. The system prompt instructs the model never to follow instructions found inside that data.

## DeepSeek Response Contract

DeepSeek must return JSON matching this conceptual schema:

```json
{
  "status": "verified | ambiguous",
  "unicode_sequence": ["U+0032"],
  "rendered_text": "2",
  "confidence": 0.99,
  "occurrences_consistent": true,
  "alternatives": ["U+00B2"],
  "evidence": ["visual glyph shape", "equation context"],
  "reason": "short explanation"
}
```

The client rejects prose outside the JSON object, invalid code points, control characters, mismatched rendered text, and unknown schema fields.

## Acceptance Gate

An LLM-proposed mapping is applied only when all conditions hold:

- `status` is `verified`;
- confidence is at least `0.98`;
- `occurrences_consistent` is true;
- every sampled occurrence is compatible with the same Unicode sequence;
- the returned sequence is one of the supplied candidates, unless the response identifies a single visually certain basic character and gives no viable alternative;
- deterministic evidence does not contradict the answer;
- the model processed image input successfully;
- the response passes schema and Unicode validation.

Otherwise the mapping remains unresolved. There is no text-only fallback and no best-effort write.

Because LLM confidence is not independently calibrated, confidence alone is never sufficient; the consistency and evidence gates are mandatory.

## Model Capability and Fail-closed Behavior

The configured model is fixed to `deepseek-v4-pro`. The client sends multimodal content in the API's supported request format and performs a capability check using a known probe image before accepting model decisions for a remediation run.

If DeepSeek rejects images, ignores the probe, times out, rate-limits the request, returns malformed JSON, or is unavailable, the stage leaves ambiguous mappings unchanged and records why they were unresolved. It must not reuse the current alt-text client's silent text fallback.

## PDF Update

For accepted mappings:

1. Append or merge `bfchar` entries into the existing `/ToUnicode` CMap.
2. Preserve its code-space ranges, existing mappings, stream filters, and font resources.
3. Apply one mapping per font/code pair, covering every occurrence that uses that font resource.
4. Save through the normal output path without changing content-stream positioning or drawing operators.

Malformed existing CMaps are reported rather than broadly rewritten unless they can be parsed and serialized without losing entries.

## Verification

After updates:

- rescan all text-showing operations and confirm repaired codes now have valid mappings;
- extract text at every repaired occurrence and confirm the expected Unicode sequence appears;
- render affected pages before and after and require no material pixel difference;
- run qpdf structural validation;
- include the results in the remediation report.

## Reporting

Each result records:

- font object, CID, affected pages, and occurrence count;
- resolution source (`font-metadata` or `deepseek-v4-pro`);
- added Unicode sequence;
- model confidence and summarized evidence when DeepSeek was used;
- unresolved reason when no change was made;
- post-write extraction and visual-verification status.

The report must never include the API key or full base64 images.

## Testing

Automated tests use synthetic and fixture PDFs to cover:

- complete CMaps producing no changes and no API calls;
- unique deterministic mappings producing no API calls;
- ambiguous mappings sending the required images and context;
- a valid high-confidence DeepSeek response adding one mapping;
- low confidence, `ambiguous`, conflicting occurrences, invalid JSON, timeout, and non-vision responses producing no change;
- shared fonts updating all occurrences once;
- Form XObject text being detected;
- supplementary-plane and multi-code-point Unicode sequences;
- preservation of existing CMap entries;
- identical affected-page rendering before and after;
- the dissertation fixture's missing superscript mapping being detected without hard-coded document knowledge.

Network calls are mocked in the standard suite. An opt-in integration test may exercise a configured DeepSeek API key without becoming a required CI dependency.

