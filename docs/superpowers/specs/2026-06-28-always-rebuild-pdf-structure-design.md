# Always Rebuild PDF Structure

## Goal

Every PDF processed through the main remediation endpoint must rebuild its semantic structure tree. Users and API clients cannot opt out per request.

## Scope

- Remove the "Rebuild structure with OpenDataLoader" checkbox from the remediation panel.
- Remove the checkbox state and conditional `overwrite_tags` request payload from the frontend.
- Remove `overwrite_tags` from the remediation request model.
- Remove the per-call `overwrite_tags` option from the full PDF remediation pipeline.
- Run OpenDataLoader structure rebuilding whenever the full PDF remediation pipeline runs.
- Retain `DISABLE_OPENDATALOADER` as an emergency deployment-level kill switch. When enabled, the remediation result must continue to state clearly that structure rebuilding was skipped.

The standalone low-level auto-tagging method may retain its overwrite argument because it controls how the tagging implementation writes an existing structure tree. The full remediation pipeline will always invoke it with overwrite enabled.

## Data Flow

1. The remediation panel submits the report ID and requests all automatable fixes without a structure-rebuild preference.
2. The `/remediate` endpoint identifies a PDF and invokes `PDFRemediator.fix_all` without a caller-controlled overwrite option.
3. Unless the deployment kill switch is active, `fix_all` invokes the auto-tagging operation with structure overwrite enabled.
4. The remediation response reports whether rebuilding succeeded or failed.

Legacy clients may still send an unknown `overwrite_tags` property. It will not control behavior; structure rebuilding remains mandatory.

## Interface Changes

- The frontend API type no longer advertises `overwrite_tags`.
- `RemediationRequest` no longer exposes `overwrite_tags` as a supported field.
- `PDFRemediator.fix_all` no longer accepts `overwrite_tags`.
- The remediation panel no longer renders a PDF-specific checkbox or warning.

## Error Handling

Tagging failures remain remediation results rather than silently bypassing the step. The deployment kill switch remains explicit and produces the existing skipped result. Other remediation operations continue according to the current pipeline behavior.

## Testing

- Add a backend regression test proving `fix_all` attempts auto-tagging by default and requests overwrite mode.
- Add an API/model regression test proving a legacy `overwrite_tags: false` value cannot disable rebuilding.
- Run the focused backend tests, then the relevant backend suite.
- Run the frontend TypeScript production build to catch stale state, props, or request types after removing the checkbox.

## Non-goals

- Changing the OpenDataLoader tagging algorithm.
- Removing the deployment-wide emergency kill switch.
- Redesigning the remediation panel.
- Changing HTML remediation.
