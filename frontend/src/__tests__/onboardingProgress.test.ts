import { describe, expect, it } from "vitest";
import { DEFAULT_SYSTEM_CONFIG } from "../api/modules/config";
import {
  DEFAULT_FIRST_CONTEXT_PROGRESS,
  restoreOnboardingProgress,
  serializeOnboardingProgress,
} from "../components/onboarding/onboardingProgress";
import { sanitizeStoredOnboardingProgress } from "../components/onboarding/onboardingStorage";

describe("onboarding progress restoration", () => {
  it("falls back safely for invalid JSON", () => {
    const restored = restoreOnboardingProgress(
      "{not-json",
      DEFAULT_SYSTEM_CONFIG,
      null,
    );

    expect(restored).toEqual(
      expect.objectContaining({
        version: 1,
        current: 0,
        seedSlug: null,
        customPersonas: [],
        firstContextProgress: DEFAULT_FIRST_CONTEXT_PROGRESS,
      }),
    );
  });

  it("rejects snapshots from an unsupported version", () => {
    const restored = restoreOnboardingProgress(
      JSON.stringify({
        version: 2,
        current: 3,
        values: DEFAULT_SYSTEM_CONFIG,
        seedSlug: "ember",
      }),
      DEFAULT_SYSTEM_CONFIG,
      null,
    );

    expect(restored.current).toBe(0);
    expect(restored.seedSlug).toBeNull();
  });

  it("sanitizes malformed first-context fields", () => {
    const restored = restoreOnboardingProgress(
      JSON.stringify({
        version: 1,
        current: 3,
        values: DEFAULT_SYSTEM_CONFIG,
        firstContextCountsByPluginId: {
          valid: 3,
          nullable: null,
          invalid: "4",
        },
        firstContextProgress: {
          route: "invalid",
          questionId: "unknown",
          seenQuestionIds: ["unknown", "easy_topic", 7],
          draft: 42,
          sessionCreationKey: " ",
          sessionId: "orphan-session",
          turnId: "turn-1",
          messageId: 9,
          historyImportJobId: " ",
          historyPreparedCount: "200",
          submitted: true,
          sendUncertain: true,
        },
      }),
      DEFAULT_SYSTEM_CONFIG,
      null,
    );

    expect(restored.firstContextCountsByPluginId).toEqual({
      valid: 3,
      nullable: null,
    });
    expect(restored.firstContextProgress).toEqual({
      ...DEFAULT_FIRST_CONTEXT_PROGRESS,
      seenQuestionIds: ["easy_topic", "preferred_name"],
      turnId: "turn-1",
    });
  });

  it("returns to model setup while retaining persona and first-context work", () => {
    const customPersona = {
      personaId: "persona-1",
      slug: "custom-1",
      name: "Custom",
      description: "Custom persona",
      config: {},
    };
    const creationDraft = {
      draftId: "draft-1",
      personaId: "persona-1",
      phase: "editing",
      description: "unfinished",
    };
    const firstContextProgress = {
      route: "history",
      questionId: "easy_topic",
      seenQuestionIds: ["preferred_name", "easy_topic"],
      draft: "retained answer",
      sessionCreationKey: "first-context-key",
      sessionId: "session-1",
      turnId: "turn-1",
      messageId: null,
      historyImportJobId: "him-retained",
      historyPreparedCount: 200,
      submitted: false,
      sendUncertain: false,
    };

    const restored = restoreOnboardingProgress(
      JSON.stringify({
        version: 1,
        current: 3,
        values: DEFAULT_SYSTEM_CONFIG,
        seedSlug: "custom-1",
        customPersonas: [customPersona],
        personaCreationDraft: creationDraft,
        firstContextPluginIds: ["chrome-history"],
        firstContextCountsByPluginId: { "chrome-history": 42 },
        firstContextProgress,
      }),
      DEFAULT_SYSTEM_CONFIG,
      null,
    );

    expect(restored.current).toBe(1);
    expect(restored.seedSlug).toBe("custom-1");
    expect(restored.customPersonas).toEqual([customPersona]);
    expect(restored.personaCreationDraft).toEqual(creationDraft);
    expect(restored.firstContextPluginIds).toEqual(["chrome-history"]);
    expect(restored.firstContextCountsByPluginId).toEqual({
      "chrome-history": 42,
    });
    expect(restored.firstContextProgress).toEqual(firstContextProgress);
  });

  it("keeps credentials server-owned and removes legacy secrets from the browser snapshot", () => {
    const backendConfig = structuredClone(DEFAULT_SYSTEM_CONFIG);
    backendConfig.llm.providers.openai = {
      enabled: true,
      provider_type: "openai",
      display_name: "OpenAI",
      provider_plan: null,
      api_key: "sk-ser****",
      base_url: "https://api.openai.com/v1",
      services: {
        chat: {
          enabled: true,
          api_key: "sk-ser****",
          base_url: "https://api.openai.com/v1",
        },
        embedding: { enabled: false, api_key: "", base_url: "" },
        image_generation: {
          enabled: false,
          api_key: "",
          base_url: "",
          timeout: 180,
          native_protocol: null,
        },
        tts: {
          enabled: false,
          api_key: "",
          base_url: "",
          model: "",
          voice: "",
          response_format: "",
        },
      },
      api_format: "openai",
      custom_models: [],
      custom_default_model: "",
      model_metadata_overrides: {},
    };
    backendConfig.llm.selections.core.provider_id = "openai";
    backendConfig.llm.selections.core.model = "gpt-5.6";

    const legacyConfig = structuredClone(backendConfig);
    legacyConfig.llm.providers.openai.api_key = "sk-legacy-browser-secret";
    legacyConfig.llm.providers.openai.services.chat.api_key =
      "sk-legacy-browser-secret";
    const restored = restoreOnboardingProgress(
      JSON.stringify({
        version: 1,
        current: 2,
        values: legacyConfig,
        seedSlug: "ember",
      }),
      backendConfig,
      null,
    );

    expect(restored.values.llm.providers.openai.api_key).toBe("sk-ser****");
    expect(restored.values.llm.providers.openai.services.chat.api_key).toBe(
      "sk-ser****",
    );

    const serialized = serializeOnboardingProgress(restored);
    expect(serialized).not.toContain("sk-legacy-browser-secret");
    expect(serialized).not.toContain("sk-ser****");
    expect(serialized).not.toContain("api_key");
    expect(JSON.parse(serialized).values).toEqual({
      preferences: { language: backendConfig.preferences.language },
    });
  });

  it("drops unknown legacy fields instead of copying possible credentials", () => {
    const sanitized = sanitizeStoredOnboardingProgress(JSON.stringify({
      version: 1,
      current: 1,
      values: {
        preferences: { language: "en" },
        llm: { providers: { openai: { api_key: "sk-values-secret" } } },
      },
      seedSlug: "ember",
      api_key: "sk-root-secret",
      unknownConfig: { token: "nested-secret" },
      customPersonas: [{
        slug: "ember",
        name: "Ember",
        apiKey: "sk-nested-allowed-secret",
        config: { authorization: "Bearer stale-token" },
      }],
    }));

    expect(sanitized).not.toBeNull();
    expect(sanitized).not.toContain("sk-values-secret");
    expect(sanitized).not.toContain("sk-root-secret");
    expect(sanitized).not.toContain("nested-secret");
    expect(sanitized).not.toContain("sk-nested-allowed-secret");
    expect(sanitized).not.toContain("stale-token");
    expect(JSON.parse(sanitized || "{}")).toEqual({
      version: 1,
      current: 1,
      values: { preferences: { language: "en" } },
      seedSlug: "ember",
      customPersonas: [{
        slug: "ember",
        name: "Ember",
        config: {},
      }],
    });
  });
});
