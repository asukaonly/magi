export const PERSONA_PREVIEW_ROUTES = [
  "picker",
  "chat",
  "profile",
  "create",
] as const;

export type PersonaPreviewRoute = (typeof PERSONA_PREVIEW_ROUTES)[number];

export function isPersonaPreviewRoute(
  value: unknown,
): value is PersonaPreviewRoute {
  return PERSONA_PREVIEW_ROUTES.some((route) => route === value);
}
