import { describe, expect, it } from "vitest";
import { DEFAULT_SYSTEM_CONFIG } from "../api/modules/config";
import {
  DEFAULT_FIRST_CONTEXT_PROGRESS,
  restoreOnboardingProgress,
} from "../components/onboarding/onboardingProgress";

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
});
