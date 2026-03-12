# LLM Provider Panel Design

## Context

The current LLM provider configuration panel in settings feels overly decorative for a system settings surface. It uses strong card framing, gradients, and repeated bordered containers that make the area look heavier than the rest of the settings UI. The detail pane also stacks explanatory copy, status UI, and controls too tightly, which causes visual crowding.

## Goals

- Keep the existing two-column information architecture.
- Shift the panel toward a flatter, system-settings visual language.
- Remove decorative gradients and heavy card borders from the provider workbench.
- Reduce copy density in the provider detail pane.
- Simplify the connection test area to a compact action plus concise status feedback.

## Design Direction

### Overall structure

Keep the current left provider list and right detail pane layout, but treat the whole area as a quiet settings surface instead of a framed feature card. The workbench should sit on a neutral background with subtle separators only.

### Left provider list

- Provider items should read like rows in a settings sidebar, not mini feature cards.
- Use flatter hover and active states with light background fills instead of shadows.
- Keep the enabled dot and active accent, but make them secondary to the label.

### Right detail pane

- Separate metadata, actions, inputs, and model references into clearer vertical groups.
- Remove the standalone "connection test" content block with descriptive prose.
- Replace it with a small utility row: provider type label, referenced-by hint if needed, enable toggle, and a single `Test` button.
- Show test results as short inline feedback below the action row.

### Inputs and model list

- Inputs should stay readable and aligned, but sit directly on the pane background.
- Available models should render as a quiet chip list with a compact heading, without its own emphasized container.

## Constraints

- No change to provider configuration behavior or API interaction.
- No change to onboarding/settings information hierarchy beyond layout cleanup.
- Existing i18n coverage must remain aligned between `zh-CN` and `en`.

## Validation

- Component tests should still cover provider testing and provider metadata rendering.
- The refreshed UI should type-check cleanly and keep current config interactions intact.
