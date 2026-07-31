export const ONBOARDING_PROGRESS_VERSION = 1;

const CREDENTIAL_FIELD_NAMES = new Set([
  "apikey",
  "token",
  "accesstoken",
  "refreshtoken",
  "secret",
  "clientsecret",
  "password",
  "authorization",
  "cookie",
  "privatekey",
  "credential",
  "credentials",
]);

export function stripOnboardingCredentialFields(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(stripOnboardingCredentialFields);
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  const sanitized: Record<string, unknown> = {};
  for (const [key, nestedValue] of Object.entries(
    value as Record<string, unknown>,
  )) {
    const normalizedKey = key.replace(/[^a-z0-9]/gi, "").toLowerCase();
    if (CREDENTIAL_FIELD_NAMES.has(normalizedKey)) {
      continue;
    }
    sanitized[key] = stripOnboardingCredentialFields(nestedValue);
  }
  return sanitized;
}

export function sanitizeStoredOnboardingProgress(
  serialized: string | null,
): string | null {
  if (!serialized) return null;
  try {
    const parsed = JSON.parse(serialized) as Record<string, unknown>;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }
    if (parsed.version !== ONBOARDING_PROGRESS_VERSION) {
      return null;
    }
    const rawValues = parsed.values;
    if (!rawValues || typeof rawValues !== "object" || Array.isArray(rawValues)) {
      return null;
    }
    const rawPreferences = (rawValues as Record<string, unknown>).preferences;
    if (
      !rawPreferences ||
      typeof rawPreferences !== "object" ||
      Array.isArray(rawPreferences)
    ) {
      return null;
    }
    const language =
      (rawPreferences as Record<string, unknown>).language === "en"
        ? "en"
        : "zh";
    return JSON.stringify({
      version: parsed.version,
      current: parsed.current,
      values: { preferences: { language } },
      seedSlug: parsed.seedSlug,
      customPersonas: stripOnboardingCredentialFields(parsed.customPersonas),
      personaCreationDraft: stripOnboardingCredentialFields(
        parsed.personaCreationDraft,
      ),
      firstContextPluginIds: stripOnboardingCredentialFields(
        parsed.firstContextPluginIds,
      ),
      firstContextCountsByPluginId: stripOnboardingCredentialFields(
        parsed.firstContextCountsByPluginId,
      ),
      firstContextProgress: stripOnboardingCredentialFields(
        parsed.firstContextProgress,
      ),
    });
  } catch {
    return null;
  }
}

export function sanitizeOnboardingProgressStorage(
  storageKey: string,
): string | null {
  const serialized = localStorage.getItem(storageKey);
  const sanitized = sanitizeStoredOnboardingProgress(serialized);
  if (sanitized) {
    localStorage.setItem(storageKey, sanitized);
  } else if (serialized) {
    localStorage.removeItem(storageKey);
  }
  return sanitized;
}
