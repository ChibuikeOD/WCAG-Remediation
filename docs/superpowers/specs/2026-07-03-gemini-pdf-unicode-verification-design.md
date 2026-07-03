# Gemini PDF Unicode Verification Design

## Goal

Use Gemini 3.1 Flash-Lite vision to verify ambiguous PDF glyph-to-Unicode mappings while preserving deterministic font evidence and fail-closed acceptance gates.

## Scope and Architecture

This applies only to ambiguous PDF Unicode repair; DeepSeek alt-text remains unchanged. A Gemini verifier calls Google's synchronous OpenAI-compatible endpoint, sends the isolated glyph and occurrence crops plus a vision probe, and reuses the existing response schema, Unicode validation, confidence threshold, consistency requirement, candidate enforcement, and rollback verification.

Configuration adds `GEMINI_API_KEY` and a Gemini endpoint while defaulting the Unicode model to `gemini-3.1-flash-lite`. Reports identify the actual provider/model. Transport, schema, probe, confidence, consistency, contradiction, and candidate failures reject the mapping without modifying the PDF.

## Verification

Tests cover payload construction, images, endpoint use, validation, provider selection, reporting, and the focused remediation contract.
