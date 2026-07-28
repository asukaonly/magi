import { act, renderHook, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  personasApi,
  type PersonaIntentResolution,
  type PersonalityConfig,
} from "../api/modules/personas";
import { runPersonaGenerationJob } from "../components/onboarding/persona-preview/personaGenerationJob";
import {
  createEmptyCreationDraft,
  type PersonaCreationDraft,
} from "../components/onboarding/persona-preview/personaPreviewModel";
import { usePersonaGenerationController } from "../components/onboarding/persona-preview/usePersonaGenerationController";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "zh-CN" },
  }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

function generatedConfig(): PersonalityConfig {
  return {
    name: "Sage",
    avatar: "",
    description: "wise mentor",
    appearance_prompt: "",
    identity_core: {
      identity_statement: "a patient mentor",
      values_loved: [],
      values_rejected: [],
      attention_biases: [],
    },
    idiolect: {
      sentence_style: "measured",
      vocab_available: [],
      vocab_avoided: [],
      structural_quirks: [],
    },
    registers: {},
    quiet_hours: [],
    signature_triggers: [],
    persona_layers: [],
    dynamic_state_rules: {},
    milestone_conditions: {},
    interim_lines: {},
    bootstrap: null,
  };
}

function ambiguousResolution(name: string): {
  success: boolean;
  message: string;
  data: PersonaIntentResolution;
} {
  return {
    success: true,
    message: "ok",
    data: {
      status: "ambiguous",
      candidates: [
        {
          candidate_id: name,
          source_kind: "fictional_reference",
          name,
          work_title: "Example",
          confidence: 0.8,
        },
      ],
      selected_candidate_id: name,
      confidence: 0.8,
      requires_confirmation: true,
      explicit_constraints: [],
    },
  };
}

function controllerOptions(initialCreationDraft: PersonaCreationDraft) {
  return {
    disabled: false,
    initialCreationDraft,
    onActiveSeedChange: vi.fn(),
    onGenerated: vi.fn(),
    onEditRequested: vi.fn(),
    clearTranscript: vi.fn(),
    registry: {
      drafts: [],
      draftsRef: { current: [] },
      replace: vi.fn(),
      upsert: vi.fn(),
    } as any,
  };
}

describe("persona generation operation ownership", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not let a superseded request unlock or overwrite its replacement", async () => {
    const first = deferred<any>();
    const second = deferred<any>();
    const resolveSpy = vi
      .spyOn(personasApi, "resolveGenerationIntent")
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const initial = {
      ...createEmptyCreationDraft(),
      description: "old description",
    };
    const { result } = renderHook(() =>
      usePersonaGenerationController(controllerOptions(initial)),
    );

    let firstRun!: Promise<void>;
    act(() => {
      firstRun = result.current.handleResolveOrGenerate();
    });
    expect(resolveSpy).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.editDescription("new description");
    });
    let secondRun!: Promise<void>;
    act(() => {
      secondRun = result.current.handleResolveOrGenerate();
    });
    expect(resolveSpy).toHaveBeenCalledTimes(2);

    await act(async () => {
      first.resolve(ambiguousResolution("old candidate"));
      await firstRun;
    });
    act(() => {
      void result.current.handleResolveOrGenerate();
    });
    expect(resolveSpy).toHaveBeenCalledTimes(2);

    await act(async () => {
      second.resolve(ambiguousResolution("new candidate"));
      await secondRun;
    });
    expect(result.current.creationDraft).toEqual(
      expect.objectContaining({
        description: "new description",
        resolution: expect.objectContaining({
          selected_candidate_id: "new candidate",
        }),
      }),
    );
  });

  it("resumes a restored start request with the same request id", async () => {
    const generationSpy = vi
      .spyOn(personasApi, "generateWithProgress")
      .mockResolvedValue({
        success: true,
        message: "ok",
        data: generatedConfig(),
        stages: [],
      });
    const restored: PersonaCreationDraft = {
      ...createEmptyCreationDraft(),
      phase: "generating",
      description: "restored request",
      referenceConfirmed: true,
      generationRequestId: "request-stable",
    };

    renderHook(
      () => usePersonaGenerationController(controllerOptions(restored)),
      { wrapper: StrictMode },
    );

    await waitFor(() => expect(generationSpy).toHaveBeenCalledTimes(1));
    expect(generationSpy.mock.calls[0][0].request_id).toBe(
      "request-stable",
    );
    expect(generationSpy.mock.calls[0][2]).toBeUndefined();
  });
});

describe("persona generation failure identity", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  const runOptions = (
    sourceDraft: PersonaCreationDraft,
    publishDraft: (draft: PersonaCreationDraft | null) => void,
  ) => ({
    sourceDraft,
    intent: {
      source_kind: "original" as const,
      reference: null,
      fidelity_level: "natural" as const,
      expression_level: "balanced" as const,
      research: {
        preference: "disabled" as const,
        force_refresh: false,
        reference_urls: [],
        identity_confidence: 1,
        identity_ambiguous: false,
        identity_verified: false,
        reference_modified: false,
        verification_fingerprint: null,
      },
      explicit_constraints: [],
    },
    disabled: false,
    targetLanguage: "Chinese" as const,
    isActive: () => true,
    publishDraft,
    setStages: vi.fn(),
    setError: vi.fn(),
    setCompatibilityRetry: vi.fn(),
    clearTranscript: vi.fn(),
    registry: { upsert: vi.fn() } as any,
    onActiveSeedChange: vi.fn(),
    onGenerated: vi.fn(),
    messages: {
      compatibilityRequired: "compatibility",
      timedOut: "timed out",
      unknownFailure: "unknown",
    },
  });

  it("preserves request and job ids when the outcome is unknown", async () => {
    vi.spyOn(personasApi, "generateWithProgress").mockRejectedValue(
      Object.assign(new Error("network unavailable"), {
        terminal: false,
        generationJobId: "job-stable",
      }),
    );
    const drafts: Array<PersonaCreationDraft | null> = [];
    const sourceDraft: PersonaCreationDraft = {
      ...createEmptyCreationDraft(),
      phase: "reviewing",
      description: "retryable",
      referenceConfirmed: true,
      generationRequestId: "request-stable",
    };

    await runPersonaGenerationJob(
      runOptions(sourceDraft, (draft) => drafts.push(draft)),
    );

    expect(drafts[drafts.length - 1]).toEqual(
      expect.objectContaining({
        phase: "failed",
        generationRequestId: "request-stable",
        generationJobId: "job-stable",
      }),
    );
  });

  it("clears request and job ids only after an explicit terminal failure", async () => {
    vi.spyOn(personasApi, "generateWithProgress").mockRejectedValue(
      Object.assign(new Error("generation failed"), {
        terminal: true,
        generationJobId: "job-terminal",
      }),
    );
    const drafts: Array<PersonaCreationDraft | null> = [];
    const sourceDraft: PersonaCreationDraft = {
      ...createEmptyCreationDraft(),
      phase: "reviewing",
      description: "terminal",
      referenceConfirmed: true,
      generationRequestId: "request-terminal",
      generationJobId: "job-terminal",
    };

    await runPersonaGenerationJob(
      runOptions(sourceDraft, (draft) => drafts.push(draft)),
    );

    expect(drafts[drafts.length - 1]).toEqual(
      expect.objectContaining({
        phase: "failed",
        generationRequestId: undefined,
        generationJobId: undefined,
      }),
    );
  });
});
