import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { i18nMock, localStorageMock, navigateMock, streamChatPreviewMock } =
  vi.hoisted(() => {
    const mock = {
      getItem: vi.fn((_key: string): string | null => null),
      setItem: vi.fn((_key: string, _value: string) => undefined),
      removeItem: vi.fn((_key: string) => undefined),
    };
    vi.stubGlobal("localStorage", mock);
    return {
      i18nMock: {
        resolvedLanguage: "zh-CN",
        language: "zh-CN",
        changeLanguage: vi.fn(),
        on: vi.fn(),
        off: vi.fn(),
      },
      localStorageMock: mock,
      navigateMock: vi.fn(),
      streamChatPreviewMock: vi.fn(),
    };
  });

import { apiClient } from "@/api/client";
import { configApi, DEFAULT_SYSTEM_CONFIG } from "@/api/modules/config";
import {
  historyImportsApi,
  type HistoryImportJob,
} from "@/api/modules/historyImports";
import { messagesApi } from "@/api/modules/messages";
import { personasApi } from "@/api/modules/personas";
import { pluginsApi } from "@/api/modules/plugins";
import * as systemSuggestions from "@/api/modules/systemSuggestions";
import OnboardingFlow from "@/components/onboarding/OnboardingFlow";
import { FIRST_CONTEXT_QUESTION_IDS } from "@/domain/chat/first-context";
import { useConversationStore } from "@/stores/conversation-store";
import { usePluginInstallPanelStore } from "@/stores/pluginInstallPanel";
import * as desktopRuntime from "@/runtime/desktop";

vi.mock("react-i18next", () => ({
  initReactI18next: {
    type: "3rdParty",
    init: vi.fn(),
  },
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: i18nMock,
  }),
}));

vi.mock("react-router", () => ({
  useNavigate: () => navigateMock,
}));

// Mock the streaming preview so persona chat does not hit the network.
vi.mock("@/api/modules/chatPreview", () => ({
  streamChatPreview: (...args: unknown[]) => streamChatPreviewMock(...args),
}));

const stubChatModel = (id: string) => ({
  id,
  capabilities: {
    vision: false,
    image_output: false,
    tool_calling: true,
    reasoning: true,
  },
  limits: { context_window: 204800, max_output_tokens: 131072 },
  hidden: false,
  preferred: false,
  source: "builtin",
  input_modalities: ["text"],
  output_modalities: ["text"],
});

const stubCatalog = () => ({
  providers: [
    {
      id: "anthropic",
      provider_type: "anthropic",
      source: "builtin",
      display_name: "Anthropic",
      default_model: "claude-sonnet-4-5",
      default_classify_model: "claude-haiku-4-5",
      default_base_url: "https://api.anthropic.com/v1",
      api_format: "anthropic",
      resolved_chat_models: [],
      resolved_embedding_models: [],
    },
    {
      id: "openai",
      provider_type: "openai",
      source: "builtin",
      display_name: "OpenAI",
      default_model: "gpt-4o",
      default_classify_model: "gpt-4o-mini",
      default_base_url: "https://api.openai.com/v1",
      api_format: "openai",
      resolved_chat_models: [],
      resolved_embedding_models: [
        { id: "text-embedding-3-small", dimensions: [1536] },
      ],
    },
    {
      id: "glm",
      provider_type: "glm",
      source: "builtin",
      display_name: "Z.ai",
      default_model: "glm-5.1",
      default_classify_model: "glm-4.6",
      default_base_url: "https://open.bigmodel.cn/api/paas/v4",
      api_format: "openai",
      resolved_chat_models: [
        stubChatModel("glm-5.1"),
        stubChatModel("glm-4.6"),
      ],
      resolved_embedding_models: [{ id: "embedding-3", dimensions: [1024] }],
      plans: [
        {
          id: "codeplan",
          display_name: "Z.ai CodePlan",
          default_model: "glm-5.1",
          default_classify_model: "glm-4.5-air",
          default_base_url: "https://open.bigmodel.cn/api/coding/paas/v4",
          allowed_scenarios: ["context_compact", "context_decider", "core"],
          endpoints: [
            {
              id: "china",
              label: "China",
              base_url: "https://open.bigmodel.cn/api/coding/paas/v4",
              api_format: "openai",
            },
          ],
          embedding_models: [],
          image_generation_models: [],
          resolved_chat_models: [
            stubChatModel("glm-5.1"),
            stubChatModel("glm-4.5-air"),
          ],
          resolved_embedding_models: [],
          resolved_image_generation_models: [],
        },
      ],
    },
  ],
});

const stubCodePlanCatalog = (): ReturnType<typeof stubCatalog> => {
  const catalog = stubCatalog();
  const glm = catalog.providers.find((provider) => provider.id === "glm");
  if (glm) {
    glm.resolved_chat_models = [
      stubChatModel("glm-5.1"),
      stubChatModel("glm-4.5-air"),
    ];
    glm.resolved_embedding_models = [];
  }
  return catalog;
};

const stubTemplate = () => ({
  template: { enabled: true, display_name: "Custom" },
  defaults: null,
});

const stubSeedPreviews = () => [
  {
    seed_slug: "nova",
    name: "Nova",
    description: "Polished assistant",
    avatar: "/avatars/nova.png",
    group: "general",
    order: 0,
  },
  {
    seed_slug: "ember",
    name: "Ember",
    description: "Deep listener",
    avatar: "/avatars/ember.png",
    group: "general",
    order: 1,
  },
];

const CUSTOM_PERSONA_ID = "11111111-1111-4111-8111-111111111111";

const stubHistoryImportJob = (quickReady = false): HistoryImportJob => ({
  job_id: "him-onboarding",
  source_type: "markdown",
  importer_plugin_id: null,
  importer_id: null,
  source_ids: ["journal.md"],
  included_source_ids: ["journal.md"],
  detected_kind: "document",
  status: quickReady ? "ready" : "preview_ready",
  total_records: 1,
  meaningful_records: 1,
  quick_target_records: 200,
  quick_max_records: 500,
  quick_imported_count: quickReady ? 1 : 0,
  imported_count: quickReady ? 1 : 0,
  projected_count: 0,
  self_participant_ids: [],
  warning_summary: {
    total_count: 0,
    codes: [],
    truncated: false,
  },
  quick_ready: quickReady,
  error_code: null,
  created_at: 1_800_000_000,
  updated_at: 1_800_000_000,
  participants: [
    {
      participant_id: "__document_author__",
      display_name: "Document author",
      is_document_author: true,
      message_count: 1,
      meaningful_count: 1,
      sample: "A quiet Sunday.",
    },
  ],
  sources: [
    {
      source_id: "journal.md",
      source_name: "journal.md",
      detected_kind: "document",
      record_count: 1,
      meaningful_count: 1,
      first_event_at: 1_800_000_000,
      last_event_at: 1_800_000_000,
      timestamp_confidence: "file_mtime",
      sample: "A quiet Sunday.",
      included: true,
    },
  ],
  preview_records: [
    {
      source_id: "journal.md",
      source_name: "journal.md",
      session_id: "journal.md",
      session_seq: 0,
      speaker_id: "__document_author__",
      speaker_name: "__document_author__",
      is_document_author: true,
      content: "# Sunday\n\nA quiet Sunday.",
      event_at: 1_800_000_000,
      timestamp_confidence: "file_mtime",
    },
  ],
});

const generatedPersonaConfig = () => ({
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
    sentence_style: "measured and kind",
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
});

async function enterPersonaStep(
  user: ReturnType<typeof userEvent.setup>,
): Promise<void> {
  await user.click(screen.getByRole("button", { name: /welcome\.getStarted/ }));
  await user.click(await screen.findByTestId("llm-setup-provider-openai"));
  await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
  const nextButton = screen.getByRole("button", { name: "actions.next" });
  await waitFor(() => expect(nextButton).toBeEnabled());
  await user.click(nextButton);
  await screen.findByRole("button", { name: /Ember/i });
}

async function enterFirstContextStep(
  user: ReturnType<typeof userEvent.setup>,
): Promise<void> {
  await enterPersonaStep(user);
  await user.click(screen.getByRole("button", { name: /Ember/i }));
  await user.click(screen.getByRole("button", { name: "actions.next" }));
  await screen.findByTestId("first-context-route-chooser");
}

async function openFirstContextActivity(
  user: ReturnType<typeof userEvent.setup>,
): Promise<void> {
  await user.click(screen.getByTestId("first-context-route-activity"));
  await screen.findByTestId("first-context-activity-route");
}

async function openFirstContextHistory(
  user: ReturnType<typeof userEvent.setup>,
): Promise<void> {
  await user.click(screen.getByTestId("first-context-route-history"));
  await screen.findByTestId("first-context-history-route");
}

describe("OnboardingFlow (linear 5-step)", () => {
  let originalUpdateLanguagePreference: unknown;
  let originalUpdateOnboardingDraft: unknown;

  beforeEach(() => {
    streamChatPreviewMock.mockReset();
    streamChatPreviewMock.mockImplementation(() =>
      (async function* () {
        yield "hi";
      })(),
    );
    originalUpdateLanguagePreference = (configApi as any)
      .updateLanguagePreference;
    originalUpdateOnboardingDraft = (configApi as any).updateOnboardingDraft;
    (configApi as any).updateLanguagePreference = vi.fn().mockResolvedValue({
      success: true,
      message: "ok",
      data: DEFAULT_SYSTEM_CONFIG,
    });
    (configApi as any).updateOnboardingDraft = vi.fn().mockResolvedValue({
      success: true,
      message: "ok",
      data: DEFAULT_SYSTEM_CONFIG,
    });
    vi.spyOn(configApi, "resolveLLMProviderCatalog").mockResolvedValue(
      stubCatalog() as any,
    );
    vi.spyOn(configApi, "getLLMCustomProviderTemplate").mockResolvedValue(
      stubTemplate() as any,
    );
    vi.spyOn(configApi, "update").mockResolvedValue({
      success: true,
      message: "ok",
      data: DEFAULT_SYSTEM_CONFIG,
    } as any);
    vi.spyOn(configApi, "getOnboardingStatus").mockResolvedValue({
      success: true,
      message: "ok",
      data: { completed: false },
    } as any);
    vi.spyOn(configApi, "testLLMProviderConnection").mockResolvedValue({
      model: "gpt-4o",
      latency_ms: 42,
      preview: "hello",
    });
    vi.spyOn(historyImportsApi, "listImporters").mockResolvedValue([]);
    vi.spyOn(pluginsApi, "getRegistry").mockResolvedValue({
      plugins: [],
      registry_version: "4",
      install_fingerprint: "registry-fingerprint",
    });
    vi.spyOn(personasApi, "seedPreviews").mockResolvedValue({
      success: true,
      data: stubSeedPreviews(),
    } as any);
    vi.spyOn(personasApi, "resolveGenerationIntent").mockResolvedValue({
      success: true,
      message: "ok",
      data: {
        status: "original",
        candidates: [],
        selected_candidate_id: null,
        confidence: 0.96,
        requires_confirmation: false,
        explicit_constraints: [],
      },
    });
    vi.spyOn(systemSuggestions, "listInstallable").mockResolvedValue({
      catalog_mode: "full",
      items: [{
        plugin_id: "chrome-history",
        name: "Chrome History",
        name_i18n: { "zh-CN": "Chrome 浏览器历史" },
        description: "Chrome history",
        description_i18n: {},
        icon: "data:image/svg+xml;base64,PHN2Zy8+",
        category: "browser_history",
        installed: false,
        rationale: { zh: "", en: "" },
        setup_time_estimate_seconds: 10,
        data_locality: "local_only",
        surfaces: { first_context: { order: 10 } },
      }],
    });
    vi.spyOn(personasApi, "seed").mockResolvedValue({
      success: true,
      data: { created_ids: [] },
    } as any);
    vi.spyOn(personasApi, "list").mockResolvedValue({
      success: true,
      data: [
        {
          persona_id: "uuid-nova",
          name: "Nova",
          slug: "nova",
          locale: "en",
          avatar_path: "",
          group_name: "general",
          sort_order: 0,
          is_builtin: true,
          seed_slug: "nova",
          description: "",
        },
        {
          persona_id: "uuid-ember",
          name: "Ember",
          slug: "ember",
          locale: "en",
          avatar_path: "",
          group_name: "general",
          sort_order: 1,
          is_builtin: true,
          seed_slug: "ember",
          description: "",
        },
      ],
    } as any);
    vi.spyOn(personasApi, "setActive").mockImplementation(
      async (personaId) => ({
        success: true,
        persona_id: personaId,
      }),
    );
    vi.spyOn(apiClient, "get").mockResolvedValue({
      data: {
        success: true,
        data: {
          ready: true,
          status: "ready",
          runtime_ready: true,
          runtime_status: "ready",
        },
      },
    } as any);
    const sessionIdsByCreationKey = new Map<string, string>();
    vi.spyOn(messagesApi, "createNewSession").mockImplementation(
      async (userId, idempotencyKey) => {
        const key = idempotencyKey || `unkeyed-${sessionIdsByCreationKey.size + 1}`;
        let sessionId = sessionIdsByCreationKey.get(key);
        if (!sessionId) {
          sessionId = `session-server-${sessionIdsByCreationKey.size + 1}`;
          sessionIdsByCreationKey.set(key, sessionId);
        }
        return {
          success: true,
          user_id: userId || "local_user",
          session_id: sessionId,
        };
      },
    );
    vi.spyOn(messagesApi, "sendMessage").mockImplementation(
      async (request) => ({
        success: true,
        message: "accepted",
        data: {
          message_id: "first-context-message",
          user_id: request.user_id || "local_user",
          session_id: request.session_id,
          turn_id: request.client_turn_id,
          message_length: request.message.length,
          timestamp: 1,
        },
      }),
    );
    vi.spyOn(messagesApi, "getHistory").mockResolvedValue({
      user_id: "local_user",
      session_id: "first-context-session",
      messages: [],
      count: 0,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    if (originalUpdateLanguagePreference === undefined) {
      delete (configApi as any).updateLanguagePreference;
    } else {
      (configApi as any).updateLanguagePreference =
        originalUpdateLanguagePreference;
    }
    if (originalUpdateOnboardingDraft === undefined) {
      delete (configApi as any).updateOnboardingDraft;
    } else {
      (configApi as any).updateOnboardingDraft = originalUpdateOnboardingDraft;
    }
    localStorageMock.getItem.mockReturnValue(null);
    localStorageMock.setItem.mockClear();
    localStorageMock.removeItem.mockClear();
    navigateMock.mockReset();
    useConversationStore.getState().reset();
    usePluginInstallPanelStore.getState().closePanel();
  });

  it("renders the welcome entrypoint with no mode cards", () => {
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    expect(screen.getByText("welcome.brand")).toBeInTheDocument();
    expect(screen.getByText("welcome.title")).toBeInTheDocument();
    expect(screen.queryByText("welcome.subtitleLine1")).not.toBeInTheDocument();
    expect(screen.queryByText("welcome.subtitleLine2")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    ).toBeInTheDocument();
    // Mode cards no longer exist anywhere in the flow.
    expect(screen.queryByText(/welcome\.quickMode/)).not.toBeInTheDocument();
    expect(screen.queryByText(/welcome\.expertMode/)).not.toBeInTheDocument();
    // No quick/expert copy anywhere on Welcome.
    expect(
      screen.queryByText(/quick mode|快速模式|expert mode|专家模式/i),
    ).toBeNull();
  });

  it("starts guided progress at model setup without counting welcome", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );

    // 步骤名同时出现在 display 标题和 rail 里,rail 项是 <li>。
    const modelStep = (await screen.findAllByText("steps.llmSetup")).find(
      (el) => el.closest("li"),
    );
    expect(modelStep?.closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.queryByText("steps.welcome")).not.toBeInTheDocument();
    expect(screen.getByText("01")).toBeInTheDocument();
    expect(screen.getByText("04")).toBeInTheDocument();

    const nextButton = screen.getByRole("button", { name: /actions\.next/ });
    expect(nextButton).toBeDisabled();
    expect(nextButton).toHaveClass("bg-primary", "disabled:bg-muted");
  });

  it("returns recovered progress to model setup before later steps", async () => {
    localStorageMock.getItem.mockImplementation((key: string) => {
      if (key !== "magi_onboarding_state") {
        return null;
      }
      return JSON.stringify({
        version: 1,
        current: 3,
        values: DEFAULT_SYSTEM_CONFIG,
        seedSlug: "ember",
      });
    });

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    expect(
      await screen.findByTestId("llm-setup-provider-openai"),
    ).toBeInTheDocument();
    expect(screen.queryByText("firstContext.title")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Ember/i }),
    ).not.toBeInTheDocument();
    expect(configApi.testLLMProviderConnection).not.toHaveBeenCalled();
  });

  it("persists the onboarding language preference as soon as it is selected", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await waitFor(() =>
      expect((configApi as any).updateLanguagePreference).toHaveBeenCalledWith(
        "zh",
      ),
    );

    await user.click(screen.getByRole("button", { name: "EN" }));

    await waitFor(() =>
      expect((configApi as any).updateLanguagePreference).toHaveBeenCalledWith(
        "en",
      ),
    );
    expect(screen.getByRole("button", { name: "EN" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      "magi_language",
      "en",
    );
  });

  it("walks through welcome → LLM setup → persona preview → first context → completion and persists seed_slug on save", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const completeOnboarding = vi
      .spyOn(configApi, "completeOnboarding")
      .mockResolvedValue({
        success: true,
        message: "ok",
        data: DEFAULT_SYSTEM_CONFIG,
      } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    // Step 0: Welcome → Get Started
    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );

    // Step 1: LLM setup — choose a flat provider card and paste the key.
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    const nextBtn = screen.getByRole("button", { name: "actions.next" });
    // Until an API key is typed, the LLM step is invalid and Next stays disabled.
    expect(nextBtn).toBeDisabled();
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    await waitFor(() => expect(nextBtn).toBeEnabled());

    const localProgressWrites = localStorageMock.setItem.mock.calls.filter(
      ([key]) => key === "magi_onboarding_state",
    );
    expect(localProgressWrites.length).toBeGreaterThan(0);
    for (const [, serialized] of localProgressWrites) {
      expect(serialized).not.toContain("sk-test");
      expect(serialized).not.toContain("api_key");
    }

    await user.click(nextBtn);

    await waitFor(() =>
      expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1),
    );
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledWith(
      expect.objectContaining({
        provider_id: "openai",
        model: "gpt-4o",
        provider: expect.objectContaining({
          api_key: "sk-test",
          services: expect.objectContaining({
            chat: expect.objectContaining({ api_key: "sk-test" }),
          }),
        }),
      }),
    );

    // Step 2: Persona preview — pick Ember (the active rail item is the
    // selection) and advance with the standard footer Next button.
    await screen.findByRole("button", { name: /Ember/i });
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await waitFor(() =>
      expect((configApi as any).updateOnboardingDraft).toHaveBeenCalledTimes(1),
    );
    const earlyPayload = (configApi as any).updateOnboardingDraft.mock
      .calls[0][0] as any;
    expect(Object.keys(earlyPayload).sort()).toEqual(["language", "llm"]);
    expect(earlyPayload.language).toBe("zh");
    expect(earlyPayload.llm.providers.openai.enabled).toBe(true);
    expect(configApi.update).not.toHaveBeenCalled();

    // Step 3: First context — this is a real step now, not a footer on completion.
    expect(await screen.findByText("firstContext.title")).toBeInTheDocument();
    expect(
      screen.getByTestId("first-context-route-question"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("first-context-route-history"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("first-context-route-activity"),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId("empty-state-connect-chrome-history"),
    ).not.toBeInTheDocument();
    await openFirstContextActivity(user);
    expect(screen.getByTestId("first-context-scope-note")).toHaveTextContent(
      "firstContext.scopeHint",
    );
    expect(
      screen.getByTestId("empty-state-connect-chrome-history"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("plugin-icon-asset")).toHaveAttribute(
      "src",
      "data:image/svg+xml;base64,PHN2Zy8+",
    );
    expect(
      screen.queryByTestId("empty-state-connect-calendar"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("firstContext.activity.kicker")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "actions.skipContext" }),
    );

    // Step 4: Completion — click Enter App. No source cards are rendered here.
    const enterApp = await screen.findByRole("button", {
      name: "actions.enterApp",
    });
    expect(screen.getByText("messages.completedDesc")).toBeInTheDocument();
    expect(
      screen.getByText("messages.completedNoteNoSources"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("messages.completedNoteWithSources"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("empty-state-connect-chrome-history"),
    ).not.toBeInTheDocument();
    await user.click(enterApp);

    await waitFor(() => expect(completeOnboarding).toHaveBeenCalledTimes(1));
    const payload = completeOnboarding.mock.calls[0][0] as any;
    expect(Object.keys(payload).sort()).toEqual(["language", "llm"]);
    expect(payload.language).toBe("zh");
    expect(payload.llm.providers.openai.enabled).toBe(true);
    expect(payload.llm.providers.openai.api_key).toBe("sk-test");
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);

    // No mode references anywhere across the rendered flow.
    expect(
      screen.queryByText(/quick mode|快速模式|expert mode|专家模式/i),
    ).toBeNull();
  });

  it("offers equal question, history, and activity routes without showing sources first", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);

    const questionRoute = screen.getByTestId("first-context-route-question");
    const historyRoute = screen.getByTestId("first-context-route-history");
    const activityRoute = screen.getByTestId("first-context-route-activity");
    // 选项改为纵向行布局(单列),为后续更多选项做准备。
    expect(questionRoute.parentElement).toHaveClass("grid-cols-1");
    expect(historyRoute.parentElement).toHaveClass("grid-cols-1");
    expect(activityRoute.parentElement).toHaveClass("grid-cols-1");
    expect(screen.getByText("firstContext.kicker")).toBeInTheDocument();
    expect(
      screen.queryByTestId("empty-state-connect-chrome-history"),
    ).not.toBeInTheDocument();

    await user.click(questionRoute);
    const input = await screen.findByTestId("first-context-story-input");
    expect(
      screen.getByTestId("first-context-question-preferred_name"),
    ).toHaveTextContent("firstContext.story.questions.preferred_name");
    expect(input).toHaveAttribute(
      "placeholder",
      "firstContext.story.placeholders.preferred_name",
    );
    expect(input).toHaveAttribute(
      "aria-describedby",
      expect.stringContaining("first-context-story-question"),
    );

    await user.type(input, "音乐、电影和旅行");
    vi.spyOn(Math, "random").mockReturnValue(0);
    await user.click(
      screen.getByRole("button", { name: "firstContext.story.changeQuestion" }),
    );
    expect(
      screen.getByTestId("first-context-question-easy_topic"),
    ).toHaveTextContent("firstContext.story.questions.easy_topic");
    expect(input).toHaveValue("音乐、电影和旅行");
    expect(input).toHaveAttribute(
      "placeholder",
      "firstContext.story.placeholders.easy_topic",
    );
    await user.clear(input);
    await user.type(input, "叫我小夏就好");

    await user.click(
      screen.getByRole("button", { name: "firstContext.routes.back" }),
    );
    await user.click(screen.getByTestId("first-context-route-question"));
    expect(await screen.findByTestId("first-context-story-input")).toHaveValue(
      "叫我小夏就好",
    );
    expect(
      screen.getByTestId("first-context-question-easy_topic"),
    ).toBeInTheDocument();

    const progressWrites = localStorageMock.setItem.mock.calls.filter(
      ([key]) => key === "magi_onboarding_state",
    );
    const persisted = JSON.parse(
      progressWrites[progressWrites.length - 1]?.[1] || "{}",
    );
    expect(persisted.firstContextProgress).toEqual(
      expect.objectContaining({
        route: "question",
        questionId: "easy_topic",
        draft: "叫我小夏就好",
      }),
    );
  });

  it("confirms a selected history import from the onboarding footer before continuing", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.spyOn(desktopRuntime, "pickMarkdownFiles").mockResolvedValue([
      "/tmp/journal.md",
    ]);
    const previewImport = vi
      .spyOn(historyImportsApi, "previewMarkdown")
      .mockResolvedValue(stubHistoryImportJob());
    const confirmImport = vi
      .spyOn(historyImportsApi, "confirm")
      .mockResolvedValue(stubHistoryImportJob(true));
    vi.spyOn(historyImportsApi, "delete").mockResolvedValue(undefined);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await openFirstContextHistory(user);

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.picker.files",
      }),
    );
    expect(await screen.findByTestId("history-import-preview")).toBeInTheDocument();
    expect(previewImport).toHaveBeenCalledWith(["/tmp/journal.md"]);
    expect(
      screen.queryByRole("button", { name: "actions.skipContext" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "actions.abandonImport" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", {
        name: "firstContext.history.preview.confirm",
      }),
    ).toHaveLength(1);

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.preview.confirm",
      }),
    );

    await waitFor(() =>
      expect(confirmImport).toHaveBeenCalledWith("him-onboarding", {
        confirmPersonalWriting: true,
        includedSourceIds: ["journal.md"],
        selfParticipantIds: [],
      }),
    );
    expect(await screen.findByTestId("history-import-ready")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "actions.abandonImport" }),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "actions.finishContext" }),
    );
    expect(
      await screen.findByRole("button", { name: "actions.enterApp" }),
    ).toBeInTheDocument();
  });

  it("requires an explicit discard before leaving an unconfirmed history import", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.spyOn(desktopRuntime, "pickMarkdownFiles").mockResolvedValue([
      "/tmp/journal.md",
    ]);
    vi.spyOn(historyImportsApi, "previewMarkdown").mockResolvedValue(
      stubHistoryImportJob(),
    );
    const discardImport = vi
      .spyOn(historyImportsApi, "delete")
      .mockResolvedValue(undefined);
    const confirmImport = vi.spyOn(historyImportsApi, "confirm");

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await openFirstContextHistory(user);
    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.picker.files",
      }),
    );
    await screen.findByTestId("history-import-preview");

    await user.click(
      screen.getByRole("button", { name: "actions.abandonImport" }),
    );

    await waitFor(() =>
      expect(discardImport).toHaveBeenCalledWith("him-onboarding"),
    );
    expect(confirmImport).not.toHaveBeenCalled();
    expect(
      await screen.findByRole("button", { name: "actions.enterApp" }),
    ).toBeInTheDocument();
  });

  it("keeps the history route anchored at the top as its content grows", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await openFirstContextHistory(user);

    const historyRoute = screen.getByTestId("first-context-history-route");
    const routeContent = historyRoute.closest(
      '[data-testid="first-context-route-content"]',
    );
    expect(routeContent).toHaveClass("mb-auto", "mt-0");
    expect(routeContent).not.toHaveClass("my-auto");
  });

  it("keeps changing questions after the whole pool has been shown", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.spyOn(Math, "random").mockReturnValue(0);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await user.click(screen.getByTestId("first-context-route-question"));

    const activeQuestionId = () => FIRST_CONTEXT_QUESTION_IDS.find(
      (questionId) => screen.queryByTestId(
        `first-context-question-${questionId}`,
      ),
    );
    let previousQuestionId = activeQuestionId();

    for (let index = 0; index < FIRST_CONTEXT_QUESTION_IDS.length + 1; index += 1) {
      await user.click(
        screen.getByRole("button", {
          name: "firstContext.story.changeQuestion",
        }),
      );
      const nextQuestionId = activeQuestionId();
      expect(nextQuestionId).toBeDefined();
      expect(nextQuestionId).not.toBe(previousQuestionId);
      previousQuestionId = nextQuestionId;
    }
  });

  it("keeps an empty personal answer on the page instead of creating a chat", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await user.click(screen.getByTestId("first-context-route-question"));
    await user.click(screen.getByTestId("first-context-story-submit"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "firstContext.story.errors.empty",
    );
    expect(messagesApi.createNewSession).not.toHaveBeenCalled();
    expect(messagesApi.sendMessage).not.toHaveBeenCalled();
  });

  it("reuses the same session when the create response is lost", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.mocked(messagesApi.createNewSession).mockRejectedValueOnce(
      new Error("response lost"),
    );
    vi.spyOn(configApi, "completeOnboarding").mockResolvedValue({
      success: true,
      message: "ok",
      data: DEFAULT_SYSTEM_CONFIG,
    } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await user.click(screen.getByTestId("first-context-route-question"));
    await user.type(
      screen.getByTestId("first-context-story-input"),
      "刚才在楼下吹了一会儿风",
    );
    await user.click(screen.getByTestId("first-context-story-submit"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "firstContext.story.errors.sessionFailed",
    );
    const stableCreationKey = vi.mocked(messagesApi.createNewSession).mock
      .calls[0][1] as string;
    expect(stableCreationKey).toMatch(/^first_context_/);
    expect(messagesApi.sendMessage).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("first-context-story-submit"));

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/chat"));
    expect(messagesApi.createNewSession).toHaveBeenCalledTimes(2);
    expect(vi.mocked(messagesApi.createNewSession).mock.calls[1][1]).toBe(
      stableCreationKey,
    );
    expect(messagesApi.sendMessage).toHaveBeenCalledWith(
      expect.objectContaining({ session_id: "session-server-1" }),
    );
  });

  it("sends a preferred name as one real message and enters that same chat", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const completeOnboarding = vi
      .spyOn(configApi, "completeOnboarding")
      .mockResolvedValue({
        success: true,
        message: "ok",
        data: DEFAULT_SYSTEM_CONFIG,
      } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await user.click(screen.getByTestId("first-context-route-question"));
    await user.type(screen.getByTestId("first-context-story-input"), "明日香");
    await user.click(screen.getByTestId("first-context-story-submit"));

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/chat"));
    expect(messagesApi.createNewSession).toHaveBeenCalledWith(
      "local_user",
      expect.stringMatching(/^first_context_/),
    );
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
    const request = vi.mocked(messagesApi.sendMessage).mock.calls[0][0];
    expect(request).toEqual(
      expect.objectContaining({
        user_id: "local_user",
        session_id: expect.stringMatching(/^session-server-/),
        message: "明日香",
        client_turn_id: expect.stringMatching(/^turn_/),
        interaction_kind: "first_context_story",
        first_context: {
          question_id: "preferred_name",
          question_text: "firstContext.story.questions.preferred_name",
        },
      }),
    );
    expect(request.metadata).toBeUndefined();
    expect(request.session_id).not.toBe(
      vi.mocked(messagesApi.createNewSession).mock.calls[0][1],
    );
    expect(completeOnboarding).toHaveBeenCalledTimes(1);
    expect(
      vi.mocked(messagesApi.sendMessage).mock.invocationCallOrder[0],
    ).toBeLessThan(completeOnboarding.mock.invocationCallOrder[0]);
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      "chat_session_local_user",
      request.session_id,
    );
    expect(localStorageMock.removeItem).toHaveBeenCalledWith(
      "magi_onboarding_state",
    );
    expect(
      screen.queryByRole("button", { name: "actions.enterApp" }),
    ).not.toBeInTheDocument();
    expect(
      useConversationStore.getState().messagesBySession[
        request.session_id
      ],
    ).toEqual([
      expect.objectContaining({
        role: "user",
        content: "明日香",
        messageId: "first-context-message",
        turnId: request.client_turn_id,
        payload: {
          interaction_kind: "first_context_story",
          first_context: {
            question_id: "preferred_name",
            question_text: "firstContext.story.questions.preferred_name",
          },
        },
      }),
    ]);
  });

  it("retries an uncertain answer with the same turn without trusting history alone", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.mocked(messagesApi.sendMessage).mockRejectedValueOnce(
      new Error("response lost"),
    );
    vi.spyOn(configApi, "completeOnboarding").mockResolvedValue({
      success: true,
      message: "ok",
      data: DEFAULT_SYSTEM_CONFIG,
    } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await user.click(screen.getByTestId("first-context-route-question"));
    await user.type(
      screen.getByTestId("first-context-story-input"),
      "今天午后的阳光很好",
    );
    await user.click(screen.getByTestId("first-context-story-submit"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "firstContext.story.errors.confirmationUnavailable",
    );
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("first-context-story-input")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "firstContext.story.changeQuestion" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "firstContext.routes.back" }),
    ).toBeDisabled();
    expect(screen.getByTestId("first-context-story-submit")).toBeEnabled();
    expect(
      screen.getByTestId(
        "first-context-story-continue-without-confirmation",
      ),
    ).toBeEnabled();
    const turnId = vi.mocked(messagesApi.sendMessage).mock.calls[0][0]
      .client_turn_id as string;
    await user.click(screen.getByTestId("first-context-story-submit"));
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/chat"));
    expect(messagesApi.getHistory).not.toHaveBeenCalled();
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(2);
    expect(
      vi.mocked(messagesApi.sendMessage).mock.calls[1][0].client_turn_id,
    ).toBe(turnId);
  });

  it("keeps the answer uncertain when the response has no message identity", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.mocked(messagesApi.sendMessage).mockResolvedValueOnce({
      success: true,
      message: "accepted",
      data: {
        user_id: "local_user",
        session_id: "first-context-session",
        turn_id: "first-context-turn",
        message_length: 8,
        timestamp: 1,
      },
    });

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await user.click(screen.getByTestId("first-context-route-question"));
    await user.type(
      screen.getByTestId("first-context-story-input"),
      "今晚循环听 MyGO",
    );
    await user.click(screen.getByTestId("first-context-story-submit"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "firstContext.story.errors.confirmationUnavailable",
    );
    expect(screen.getByTestId("first-context-story-input")).toBeDisabled();
    expect(
      screen.getByTestId(
        "first-context-story-continue-without-confirmation",
      ),
    ).toBeEnabled();
    expect(navigateMock).not.toHaveBeenCalled();
  });

  it("lets the user enter Magi when send confirmation remains unavailable", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.mocked(messagesApi.sendMessage).mockRejectedValueOnce(
      new Error("response lost"),
    );
    const completeOnboarding = vi
      .spyOn(configApi, "completeOnboarding")
      .mockResolvedValue({
        success: true,
        message: "ok",
        data: DEFAULT_SYSTEM_CONFIG,
      } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await user.click(screen.getByTestId("first-context-route-question"));
    await user.type(
      screen.getByTestId("first-context-story-input"),
      "今天想慢一点",
    );
    await user.click(screen.getByTestId("first-context-story-submit"));

    await user.click(
      await screen.findByTestId(
        "first-context-story-continue-without-confirmation",
      ),
    );

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/chat"));
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
    expect(completeOnboarding).toHaveBeenCalledTimes(1);
  });

  it("unlocks a definitively rejected answer without exposing backend details", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.mocked(messagesApi.sendMessage).mockResolvedValueOnce({
      success: false,
      message: "Runtime command enqueue failed",
      data: {
        user_id: "local_user",
        session_id: "first-context-session",
        turn_id: "first-context-turn",
        message_length: 12,
        timestamp: 1,
      },
    });

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await user.click(screen.getByTestId("first-context-route-question"));
    await user.type(
      screen.getByTestId("first-context-story-input"),
      "最近晚饭后总想出去走一圈",
    );
    await user.click(screen.getByTestId("first-context-story-submit"));

    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent("firstContext.story.errors.sendFailed");
    expect(error).not.toHaveTextContent("Runtime command enqueue failed");
    expect(screen.getByTestId("first-context-story-input")).toBeEnabled();
    expect(
      screen.queryByTestId(
        "first-context-story-continue-without-confirmation",
      ),
    ).not.toBeInTheDocument();
  });

  it("retries onboarding completion without sending the answer twice", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const completeOnboarding = vi
      .spyOn(configApi, "completeOnboarding")
      .mockRejectedValueOnce(new Error("save unavailable"))
      .mockResolvedValueOnce({
        success: true,
        message: "ok",
        data: DEFAULT_SYSTEM_CONFIG,
      } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await user.click(screen.getByTestId("first-context-route-question"));
    await user.type(
      screen.getByTestId("first-context-story-input"),
      "最近下班后喜欢慢慢走回家",
    );
    await user.click(screen.getByTestId("first-context-story-submit"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "firstContext.story.errors.finishFailed",
    );
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("first-context-story-input")).toHaveValue(
      "最近下班后喜欢慢慢走回家",
    );
    expect(screen.getByTestId("first-context-story-input")).toBeDisabled();
    expect(screen.getByTestId("first-context-story-submit")).toHaveTextContent(
      "firstContext.story.retryEntering",
    );

    await user.click(screen.getByTestId("first-context-story-submit"));
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/chat"));
    expect(completeOnboarding).toHaveBeenCalledTimes(2);
    expect(messagesApi.sendMessage).toHaveBeenCalledTimes(1);
  });

  it("keeps the draft when the runtime is not ready", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterFirstContextStep(user);
    await user.click(screen.getByTestId("first-context-route-question"));
    await user.type(
      screen.getByTestId("first-context-story-input"),
      "今天什么都不想赶",
    );
    let simulatedNow = 0;
    vi.spyOn(Date, "now").mockImplementation(() => {
      simulatedNow += 13_000;
      return simulatedNow;
    });
    await user.click(screen.getByTestId("first-context-story-submit"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "firstContext.story.errors.runtimeNotReady",
    );
    expect(screen.getByTestId("first-context-story-input")).toHaveValue(
      "今天什么都不想赶",
    );
    expect(screen.getByTestId("first-context-story-input")).toBeEnabled();
    expect(messagesApi.createNewSession).not.toHaveBeenCalled();
    expect(messagesApi.sendMessage).not.toHaveBeenCalled();
  });

  it("restores the selected question and draft after model revalidation", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockImplementation((key: string) => {
      if (key !== "magi_onboarding_state") {
        return null;
      }
      return JSON.stringify({
        version: 1,
        current: 3,
        values: DEFAULT_SYSTEM_CONFIG,
        seedSlug: "ember",
        firstContextProgress: {
          route: "question",
          questionId: "personal_time",
          draft: "晚上洗完澡以后最像自己的时间",
          sessionCreationKey: "first_context_restored",
          sessionId: "restored-session",
          turnId: "restored-turn",
          submitted: false,
          sendUncertain: false,
        },
      });
    });

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await screen.findByRole("button", { name: /Ember/i });
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    expect(
      await screen.findByTestId("first-context-question-personal_time"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("first-context-story-input")).toHaveValue(
      "晚上洗完澡以后最像自己的时间",
    );
  });

  it("preserves the chosen persona after moving forward and back", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    const ember = await screen.findByRole("button", { name: /Ember/i });
    await user.click(ember);
    // 点卡片只选中不跳转,仍停留在 picker。
    expect(ember).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await screen.findByText("firstContext.title");
    await user.click(screen.getByRole("button", { name: "actions.previous" }));

    expect(
      await screen.findByRole("button", { name: /Ember/i }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Nova/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await screen.findByText("firstContext.title");
    expect(personasApi.setActive).toHaveBeenCalledTimes(1);
  });

  it("uses the welcome language for persona previews and final persona setup", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const completeOnboarding = vi
      .spyOn(configApi, "completeOnboarding")
      .mockResolvedValue({
        success: true,
        message: "ok",
        data: DEFAULT_SYSTEM_CONFIG,
      } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await waitFor(() =>
      expect(personasApi.seedPreviews).toHaveBeenCalledWith("zh"),
    );
    await user.click(screen.getByRole("button", { name: "EN" }));
    await waitFor(() =>
      expect(personasApi.seedPreviews).toHaveBeenCalledWith("en"),
    );
    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );

    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await user.click(await screen.findByTestId("persona-chat-ember"));
    await user.type(
      screen.getByPlaceholderText(/composerPlaceholder/i),
      "hello",
    );
    await user.click(
      screen.getByRole("button", { name: /^(personaPreview\.)?send$/i }),
    );
    await waitFor(() =>
      expect(streamChatPreviewMock).toHaveBeenCalledWith(
        expect.objectContaining({ seed_slug: "ember", locale: "en" }),
      ),
    );

    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await user.click(
      await screen.findByRole("button", { name: "actions.skipContext" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "actions.enterApp" }),
    );

    await waitFor(() => expect(completeOnboarding).toHaveBeenCalledTimes(1));
    expect(completeOnboarding).toHaveBeenCalledWith(
      expect.objectContaining({ language: "en" }),
    );
    expect(personasApi.seed).toHaveBeenCalledWith("en");
  });

  it("automatically validates a keyless custom OpenAI-compatible endpoint", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-custom"));
    await user.type(
      screen.getByTestId("llm-setup-base-url"),
      "http://127.0.0.1:11434/v1",
    );
    await user.type(
      screen.getByTestId("llm-setup-custom-model"),
      "local-model",
    );
    const nextButton = screen.getByRole("button", { name: "actions.next" });
    await waitFor(() => expect(nextButton).toBeEnabled());
    await user.click(nextButton);

    await screen.findByRole("button", { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledWith(
      expect.objectContaining({
        model: "local-model",
        provider: expect.objectContaining({
          provider_type: "custom",
          api_key: "",
          base_url: "http://127.0.0.1:11434/v1",
        }),
      }),
    );
  });

  it("reuses a successful manual model test after returning from persona", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    await user.click(
      screen.getByRole("button", { name: "llmSetup.verifyConnection" }),
    );
    expect(
      await screen.findByText("llm.providerConfiguration.testSuccess"),
    ).toBeInTheDocument();
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await screen.findByRole("button", { name: /Ember/i });
    await user.click(screen.getByRole("button", { name: "actions.previous" }));

    expect(
      await screen.findByText("llm.providerConfiguration.testSuccess"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await screen.findByRole("button", { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);
  });

  it("invalidates a successful test as soon as the provider plan changes", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-glm"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "glm-key");
    await user.click(
      screen.getByRole("button", { name: "llmSetup.verifyConnection" }),
    );
    expect(
      await screen.findByText("llm.providerConfiguration.testSuccess"),
    ).toBeInTheDocument();
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);

    let resolvePlanCatalog:
      ((value: ReturnType<typeof stubCatalog>) => void) | undefined;
    const pendingPlanCatalog = new Promise<ReturnType<typeof stubCatalog>>(
      (resolve) => {
        resolvePlanCatalog = resolve;
      },
    );
    vi.mocked(configApi.resolveLLMProviderCatalog).mockReturnValueOnce(
      pendingPlanCatalog as any,
    );

    await user.click(screen.getByText("llm.providerPlans.default"));
    await user.click(await screen.findByText("Z.ai CodePlan"));
    expect(
      screen.getByText("llm.providerConfiguration.testSuccess"),
    ).toBeInTheDocument();
    const nextButton = screen.getByRole("button", { name: "actions.next" });
    const previousButton = screen.getByRole("button", {
      name: "actions.previous",
    });
    expect(nextButton).toBeDisabled();
    expect(previousButton).toBeDisabled();
    expect(screen.getByTestId("llm-setup-api-key")).toBeDisabled();
    resolvePlanCatalog?.(stubCodePlanCatalog());
    await waitFor(() => expect(nextButton).toBeEnabled());
    expect(previousButton).toBeEnabled();
    expect(screen.getByTestId("llm-setup-api-key")).toBeEnabled();
    expect(
      screen.queryByText("llm.providerConfiguration.testSuccess"),
    ).not.toBeInTheDocument();
    await user.click(nextButton);

    await screen.findByRole("button", { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(2);
    expect(configApi.testLLMProviderConnection).toHaveBeenLastCalledWith(
      expect.objectContaining({
        model: "glm-5.1",
        provider: expect.objectContaining({ provider_plan: "codeplan" }),
      }),
    );
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await waitFor(() =>
      expect(configApi.updateOnboardingDraft).toHaveBeenCalledTimes(2),
    );
    const draftPayload = vi.mocked(configApi.updateOnboardingDraft).mock
      .calls[1][0] as any;
    expect(draftPayload.llm.selections.context_decider.model).toBe(
      "glm-4.5-air",
    );
    expect(
      draftPayload.llm.selections.context_decider.limits.context_window,
    ).toBe(204800);
    expect(draftPayload.llm.selections.memory_summarizer.provider_id).toBe("");
    expect(draftPayload.llm.selections.memory_summarizer.model).toBe("");
  });

  it("keeps the previous provider settings when plan resolution fails", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-glm"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "glm-key");
    await user.click(
      screen.getByRole("button", { name: "llmSetup.verifyConnection" }),
    );
    expect(
      await screen.findByText("llm.providerConfiguration.testSuccess"),
    ).toBeInTheDocument();
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);

    let rejectPlanCatalog: ((reason?: unknown) => void) | undefined;
    const pendingPlanCatalog = new Promise<ReturnType<typeof stubCatalog>>(
      (_, reject) => {
        rejectPlanCatalog = reject;
      },
    );
    vi.mocked(configApi.resolveLLMProviderCatalog).mockReturnValueOnce(
      pendingPlanCatalog as any,
    );

    await user.click(screen.getByText("llm.providerPlans.default"));
    await user.click(await screen.findByText("Z.ai CodePlan"));
    const nextButton = screen.getByRole("button", { name: "actions.next" });
    const previousButton = screen.getByRole("button", {
      name: "actions.previous",
    });
    expect(nextButton).toBeDisabled();
    expect(previousButton).toBeDisabled();

    rejectPlanCatalog?.(new Error("catalog unavailable"));
    expect(
      await screen.findByText("llmSetup.planLoadFailed"),
    ).toBeInTheDocument();
    await waitFor(() => expect(nextButton).toBeEnabled());
    expect(previousButton).toBeEnabled();
    expect(
      screen.getByText("llm.providerConfiguration.testSuccess"),
    ).toBeInTheDocument();
    await user.click(nextButton);

    await screen.findByRole("button", { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);
    expect(configApi.testLLMProviderConnection).toHaveBeenLastCalledWith(
      expect.objectContaining({
        model: "glm-5.1",
        provider: expect.objectContaining({ provider_plan: null }),
      }),
    );
  });

  it("tests again after the API key changes", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    const keyInput = screen.getByTestId("llm-setup-api-key");
    await user.type(keyInput, "sk-first");
    await user.click(
      screen.getByRole("button", { name: "llmSetup.verifyConnection" }),
    );
    expect(
      await screen.findByText("llm.providerConfiguration.testSuccess"),
    ).toBeInTheDocument();

    await user.clear(keyInput);
    await user.type(keyInput, "sk-second");
    await waitFor(() =>
      expect(
        screen.queryByText("llm.providerConfiguration.testSuccess"),
      ).not.toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await screen.findByRole("button", { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(2);
  });

  it("tests again after the primary model changes", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    await user.click(
      screen.getByRole("button", { name: "llmSetup.verifyConnection" }),
    );
    expect(
      await screen.findByText("llm.providerConfiguration.testSuccess"),
    ).toBeInTheDocument();

    await user.click(screen.getByTestId("llm-setup-advanced-toggle"));
    const modelInput = screen.getByTestId("llm-setup-core-model");
    await user.clear(modelInput);
    await user.type(modelInput, "gpt-4.1");
    await waitFor(() =>
      expect(
        screen.queryByText("llm.providerConfiguration.testSuccess"),
      ).not.toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await screen.findByRole("button", { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(2);
    expect(configApi.testLLMProviderConnection).toHaveBeenLastCalledWith(
      expect.objectContaining({ model: "gpt-4.1" }),
    );
  });

  it("reuses success after a fast-model change but retests after the endpoint changes", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    await user.click(
      screen.getByRole("button", { name: "llmSetup.verifyConnection" }),
    );
    expect(
      await screen.findByText("llm.providerConfiguration.testSuccess"),
    ).toBeInTheDocument();

    await user.click(screen.getByTestId("llm-setup-advanced-toggle"));
    const fastModelInput = screen.getByTestId("llm-setup-fast-model");
    await user.clear(fastModelInput);
    await user.type(fastModelInput, "gpt-4o-mini-new");
    expect(
      screen.getByText("llm.providerConfiguration.testSuccess"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await screen.findByRole("button", { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "actions.previous" }));

    await user.click(await screen.findByTestId("llm-setup-advanced-toggle"));
    const baseUrlInput = await screen.findByTestId("llm-setup-base-url");
    await user.clear(baseUrlInput);
    await user.type(baseUrlInput, "https://relay.example.com/v1");
    await waitFor(() =>
      expect(
        screen.queryByText("llm.providerConfiguration.testSuccess"),
      ).not.toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await screen.findByRole("button", { name: /Ember/i });
    expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(2);
    expect(configApi.testLLMProviderConnection).toHaveBeenLastCalledWith(
      expect.objectContaining({
        provider: expect.objectContaining({
          base_url: "https://relay.example.com/v1",
        }),
      }),
    );
  });

  it("stays on model setup when automatic validation fails", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.mocked(configApi.testLLMProviderConnection).mockRejectedValueOnce(
      new Error("invalid credentials"),
    );

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "bad-key");
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    expect(
      await screen.findByText("llm.providerConfiguration.testFailed"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("llm-setup-api-key")).toHaveValue("bad-key");
    expect(
      screen.queryByRole("button", { name: /Ember/i }),
    ).not.toBeInTheDocument();
  });

  it("clears recovered service keys and tests the newly entered common endpoint", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const initialConfig = structuredClone(DEFAULT_SYSTEM_CONFIG);
    initialConfig.llm.providers.custom = {
      enabled: true,
      provider_type: "custom",
      display_name: "Local service",
      provider_plan: null,
      api_key: "***",
      base_url: "https://old.example/v1",
      services: {
        chat: {
          enabled: true,
          api_key: "***",
          base_url: "https://old-chat.example/v1",
        },
        embedding: {
          enabled: true,
          api_key: "***",
          base_url: "https://old-embedding.example/v1",
        },
        image_generation: {
          enabled: true,
          api_key: "***",
          base_url: "https://old-image.example/v1",
          timeout: 180,
          native_protocol: null,
        },
        tts: {
          enabled: true,
          api_key: "***",
          base_url: "https://old-tts.example/v1",
          model: "",
          voice: "",
          response_format: "",
        },
      },
      api_format: "openai",
      custom_models: ["local-model"],
      custom_default_model: "local-model",
      model_metadata_overrides: {},
    };
    initialConfig.llm.selections.core.provider_id = "custom";
    initialConfig.llm.selections.core.model = "local-model";
    initialConfig.llm.selections.context_decider.provider_id = "custom";
    initialConfig.llm.selections.context_decider.model = "local-model";

    render(<OnboardingFlow initialConfig={initialConfig} />);
    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    const keyInput = await screen.findByTestId("llm-setup-api-key");
    await user.clear(keyInput);
    const baseUrlInput = screen.getByTestId("llm-setup-base-url");
    await user.clear(baseUrlInput);
    await user.type(baseUrlInput, "http://127.0.0.1:11434/v1");
    await user.click(
      screen.getByRole("button", { name: "llmSetup.verifyConnection" }),
    );

    await waitFor(() =>
      expect(configApi.testLLMProviderConnection).toHaveBeenCalledTimes(1),
    );
    const testedProvider = vi.mocked(configApi.testLLMProviderConnection).mock
      .calls[0][0].provider;
    expect(testedProvider.api_key).toBe("");
    expect(testedProvider.base_url).toBe("http://127.0.0.1:11434/v1");
    expect(testedProvider.services.chat.api_key).toBe("");
    expect(testedProvider.services.chat.base_url).toBe(
      "http://127.0.0.1:11434/v1",
    );
    for (const serviceName of [
      "embedding",
      "image_generation",
      "tts",
    ] as const) {
      const service = testedProvider.services[serviceName];
      expect(service.api_key).toBe("");
      expect(service.base_url).toBe("");
    }

    await waitFor(() =>
      expect(configApi.updateOnboardingDraft).toHaveBeenCalledTimes(1),
    );
    const savedProvider = vi.mocked(configApi.updateOnboardingDraft).mock
      .calls[0][0].llm.providers.custom;
    expect(savedProvider.api_key).toBe("");
    expect(savedProvider.base_url).toBe("http://127.0.0.1:11434/v1");
    for (const service of Object.values(savedProvider.services)) {
      expect(service.api_key).toBe("");
      expect(service.base_url).toBe("");
    }
  });

  it("enters the app when completion was saved but the response was lost", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.spyOn(configApi, "completeOnboarding").mockRejectedValue(
      new Error("response lost"),
    );
    vi.mocked(configApi.getOnboardingStatus).mockResolvedValue({
      success: true,
      message: "ok",
      data: { completed: true },
    } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    const nextBtn = screen.getByRole("button", { name: "actions.next" });
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    await screen.findByRole("button", { name: /Ember/i });
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await screen.findByText("firstContext.title");
    await user.click(
      screen.getByRole("button", { name: "actions.skipContext" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "actions.enterApp" }),
    );

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/"));
    expect(localStorageMock.removeItem).toHaveBeenCalledWith(
      "magi_onboarding_state",
    );
  });

  it("keeps the first-context step open after a selected source finishes connecting", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const openPanel = vi.spyOn(
      usePluginInstallPanelStore.getState(),
      "openPanel",
    );

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    const nextBtn = screen.getByRole("button", { name: "actions.next" });
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    await screen.findByRole("button", { name: /Ember/i });
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await screen.findByText("firstContext.title");
    await openFirstContextActivity(user);
    await user.click(screen.getByTestId("empty-state-connect-chrome-history"));

    expect(openPanel).toHaveBeenCalledWith("chrome-history", expect.objectContaining({
      install: true,
      context: "first_context",
      onDone: expect.any(Function),
      pluginIcon: "data:image/svg+xml;base64,PHN2Zy8+",
      pluginName: "Chrome 浏览器历史",
    }));
    expect(screen.getByText("firstContext.activity.title")).toBeInTheDocument();

    const onDone = openPanel.mock.calls[0]?.[1]?.onDone;
    onDone?.({ pluginId: "chrome-history", firstContextCount: 42 });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "actions.finishContext" }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("firstContext.connectedCount")).toBeInTheDocument();
    expect(screen.getByText("Chrome 浏览器历史")).toBeInTheDocument();
    expect(screen.getByText("firstContext.preparedCount")).toBeInTheDocument();
    expect(
      screen.queryByTestId("empty-state-connect-chrome-history"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("emptyState.noAvailable")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "actions.enterApp" }),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "actions.finishContext" }),
    );
    expect(
      await screen.findByRole("button", { name: "actions.enterApp" }),
    ).toBeInTheDocument();
    expect(screen.getByText("messages.completedDesc")).toBeInTheDocument();
    expect(
      screen.getByText("messages.completedNoteWithSources"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("messages.completedNoteNoSources"),
    ).not.toBeInTheDocument();
  });

  it("offers retry when first-context recommendations fail to load", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.mocked(systemSuggestions.listInstallable)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({
        catalog_mode: "full",
        items: [{
          plugin_id: "chrome-history",
          name: "Chrome History",
          name_i18n: { "zh-CN": "Chrome 浏览器历史" },
          description: "Chrome history",
          description_i18n: {},
          icon: "data:image/svg+xml;base64,PHN2Zy8+",
          category: "browser_history",
          installed: false,
          rationale: { zh: "", en: "" },
          setup_time_estimate_seconds: 10,
          data_locality: "local_only",
          surfaces: { first_context: { order: 10 } },
        }],
      });

    render(
      <StrictMode>
        <OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />
      </StrictMode>,
    );

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await screen.findByRole("button", { name: /Ember/i });
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await screen.findByText("firstContext.title");
    await openFirstContextActivity(user);
    expect(await screen.findByText("emptyState.loadError")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "actions.skipContext" }),
    ).toBeEnabled();
    expect(
      screen.queryByTestId(/empty-state-connect-/),
    ).not.toBeInTheDocument();
    await user.click(screen.getByTestId("empty-state-retry"));
    expect(
      await screen.findByTestId("empty-state-connect-chrome-history"),
    ).toBeInTheDocument();
    expect(systemSuggestions.listInstallable).toHaveBeenCalledTimes(2);
  });

  it("keeps onboarding skippable when only the local plugin catalog is available", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.mocked(systemSuggestions.listInstallable).mockResolvedValue({
      items: [],
      catalog_mode: "installed_only",
    });

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await screen.findByRole("button", { name: /Ember/i });
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await screen.findByText("firstContext.title");
    await openFirstContextActivity(user);
    expect(
      await screen.findByText("emptyState.marketplaceUnavailableTitle"),
    ).toBeInTheDocument();
    expect(screen.queryByText("emptyState.noAvailable")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "actions.skipContext" }),
    ).toBeEnabled();
  });

  it("surfaces the embedding-fallback row when an Anthropic-style provider is picked", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );

    await user.click(await screen.findByTestId("llm-setup-provider-anthropic"));

    await waitFor(() =>
      expect(screen.getByTestId("llm-setup-embedding-row")).toBeInTheDocument(),
    );
  });

  it("shows the missing-vector warning only inside the activity route", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-anthropic"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "actions.next" }),
      ).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await screen.findByRole("button", { name: /Ember/i });
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await screen.findByTestId("first-context-route-chooser");
    expect(
      screen.queryByTestId("first-context-memory-warning"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByTestId("first-context-route-question"));
    expect(
      screen.queryByTestId("first-context-memory-warning"),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "firstContext.routes.back" }),
    );
    await openFirstContextActivity(user);
    expect(
      await screen.findByTestId("first-context-memory-warning"),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "actions.skipContext" }),
    );
    expect(
      await screen.findByRole("button", { name: "actions.enterApp" }),
    ).toBeInTheDocument();
  });

  it("persists verified model setup before activating the chosen persona", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const completeOnboarding = vi
      .spyOn(configApi, "completeOnboarding")
      .mockResolvedValue({
        success: true,
        message: "ok",
        data: DEFAULT_SYSTEM_CONFIG,
      } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    const nextBtn = screen.getByRole("button", { name: "actions.next" });
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    await screen.findByRole("button", { name: /Ember/i });
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await waitFor(() =>
      expect(personasApi.setActive).toHaveBeenCalledWith("uuid-ember"),
    );
    await screen.findByText("firstContext.title");
    expect(configApi.updateOnboardingDraft).toHaveBeenCalledTimes(1);
    expect(
      vi.mocked(configApi.updateOnboardingDraft).mock.invocationCallOrder[0],
    ).toBeLessThan(
      vi.mocked(personasApi.setActive).mock.invocationCallOrder[0],
    );
    expect(completeOnboarding).not.toHaveBeenCalled();
  });

  it("keeps persona activation failures on the persona step and retries successfully", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const completeOnboarding = vi
      .spyOn(configApi, "completeOnboarding")
      .mockResolvedValue({
        success: true,
        message: "ok",
        data: DEFAULT_SYSTEM_CONFIG,
      } as any);
    vi.mocked(personasApi.setActive)
      .mockRejectedValueOnce(new Error("activation unavailable"))
      .mockResolvedValueOnce({ success: true, persona_id: "uuid-ember" });

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterPersonaStep(user);
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "messages.personaActivationFailed",
    );
    expect(screen.getByTestId("persona-pick-ember")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(configApi.updateOnboardingDraft).toHaveBeenCalledTimes(1);
    expect(completeOnboarding).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await screen.findByText("firstContext.title");
    expect(personasApi.setActive).toHaveBeenCalledTimes(2);
    expect(configApi.updateOnboardingDraft).toHaveBeenCalledTimes(1);
  });

  it("does not activate a custom persona that only shares the selected builtin slug", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.mocked(personasApi.list).mockResolvedValueOnce({
      success: true,
      data: [
        {
          persona_id: "uuid-custom-ember",
          name: "Ember copy",
          slug: "ember",
          locale: "zh",
          avatar_path: "",
          group_name: "custom",
          sort_order: 0,
          is_builtin: false,
          seed_slug: null,
          description: "",
        },
      ],
    } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterPersonaStep(user);
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "messages.personaUnavailable",
    );
    expect(personasApi.setActive).not.toHaveBeenCalled();
    expect(configApi.updateOnboardingDraft).toHaveBeenCalledTimes(1);
  });

  it("blocks progress when the active-persona response names a different persona", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.mocked(personasApi.setActive).mockResolvedValueOnce({
      success: true,
      persona_id: "uuid-nova",
    });

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterPersonaStep(user);
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "messages.personaActivationFailed",
    );
    expect(configApi.updateOnboardingDraft).toHaveBeenCalledTimes(1);
  });

  it("disables persona controls and navigation while activation is pending", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    let resolveActivation:
      ((value: { success: boolean; persona_id: string }) => void) | undefined;
    vi.mocked(personasApi.setActive).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveActivation = resolve;
        }),
    );

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterPersonaStep(user);
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await waitFor(() => expect(personasApi.setActive).toHaveBeenCalled());

    expect(screen.getByTestId("persona-pick-ember")).toBeDisabled();
    expect(screen.getByTestId("persona-create-custom")).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "actions.previous" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "actions.activatingPersona" }),
    ).toBeDisabled();

    resolveActivation?.({ success: true, persona_id: "uuid-ember" });
    await screen.findByText("firstContext.title");
  });

  it("prevents a timed-out seed request from activating an obsolete selection later", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    const originalSetTimeout = window.setTimeout.bind(window);
    vi.spyOn(window, "setTimeout").mockImplementation(
      (handler, timeout, ...args) =>
        originalSetTimeout(handler, timeout === 15_000 ? 0 : timeout, ...args),
    );
    let resolveOldSeed: ((value: unknown) => void) | undefined;
    vi.mocked(personasApi.seed)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveOldSeed = resolve;
          }) as any,
      )
      .mockResolvedValueOnce({
        success: true,
        data: { created_ids: [] },
      } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterPersonaStep(user);
    await user.click(screen.getByRole("button", { name: /Ember/i }));
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "messages.personaSetupTimedOut",
    );
    await user.click(screen.getByTestId("persona-pick-nova"));
    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await screen.findByText("firstContext.title");
    expect(personasApi.setActive).toHaveBeenCalledTimes(1);
    expect(personasApi.setActive).toHaveBeenCalledWith("uuid-nova");
    expect(personasApi.list).toHaveBeenCalledTimes(1);

    resolveOldSeed?.({ success: true, data: { created_ids: [] } });
    await waitFor(() => expect(personasApi.seed).toHaveBeenCalledTimes(2));
    expect(personasApi.list).toHaveBeenCalledTimes(1);
    expect(personasApi.setActive).toHaveBeenCalledTimes(1);
    expect(configApi.updateOnboardingDraft).toHaveBeenCalledTimes(1);
  });

  it("creates and activates a custom generated persona before leaving the persona step", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      CUSTOM_PERSONA_ID,
    );
    const completeOnboarding = vi
      .spyOn(configApi, "completeOnboarding")
      .mockResolvedValue({
        success: true,
        message: "ok",
        data: DEFAULT_SYSTEM_CONFIG,
      } as any);
    const generated = generatedPersonaConfig();
    vi.spyOn(personasApi, "generateWithProgress").mockResolvedValue({
      success: true,
      message: "ok",
      data: generated,
      stages: [],
    } as any);
    const createSpy = vi.spyOn(personasApi, "create").mockResolvedValue({
      success: true,
      data: {
        persona_id: CUSTOM_PERSONA_ID,
        name: "Sage",
        slug: `onboarding-custom-${CUSTOM_PERSONA_ID}`,
      },
    } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    const nextBtn = screen.getByRole("button", { name: "actions.next" });
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    // Persona step: generate a custom persona, which auto-selects it.
    await user.click(await screen.findByTestId("persona-create-custom"));
    await user.type(
      screen.getByTestId("persona-custom-description"),
      "a wise mentor",
    );
    await user.click(screen.getByTestId("persona-custom-generate"));
    // Back in chat mode with the custom persona selected — advance.
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "actions.next" }),
      ).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await waitFor(() => expect(createSpy).toHaveBeenCalled());
    const createArg = createSpy.mock.calls[0][0] as {
      persona_id: string;
      slug: string;
      locale: string;
      config_json: string;
    };
    expect(createArg.persona_id).toBe(CUSTOM_PERSONA_ID);
    expect(createArg.slug).toBe(`onboarding-custom-${CUSTOM_PERSONA_ID}`);
    expect(createArg.locale).toBe("zh");
    expect(JSON.parse(createArg.config_json).name).toBe("Sage");
    expect(personasApi.setActive).toHaveBeenCalledWith(CUSTOM_PERSONA_ID);
    await screen.findByText("firstContext.title");
    expect(completeOnboarding).not.toHaveBeenCalled();

    const persistedDraftCall = localStorageMock.setItem.mock.calls.findIndex(
      ([key, value]) =>
        key === "magi_onboarding_state" && value.includes(CUSTOM_PERSONA_ID),
    );
    expect(persistedDraftCall).toBeGreaterThanOrEqual(0);
    expect(
      localStorageMock.setItem.mock.invocationCallOrder[persistedDraftCall],
    ).toBeLessThan(createSpy.mock.invocationCallOrder[0]);

    await user.click(
      screen.getByRole("button", { name: "actions.skipContext" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "actions.enterApp" }),
    );
    await waitFor(() => expect(completeOnboarding).toHaveBeenCalledTimes(1));
    expect(createSpy).toHaveBeenCalledTimes(1);
    expect(personasApi.setActive).toHaveBeenCalledTimes(1);
  });

  it("persists an unfinished custom persona description before generation", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterPersonaStep(user);
    await user.click(screen.getByTestId("persona-create-custom"));
    await user.type(
      screen.getByTestId("persona-custom-description"),
      "孙悟空，但还没选作品",
    );

    const progressWrites = localStorageMock.setItem.mock.calls.filter(
      ([key]) => key === "magi_onboarding_state",
    );
    const persisted = JSON.parse(
      progressWrites[progressWrites.length - 1]?.[1] || "{}",
    );

    expect(persisted.personaCreationDraft).toEqual(
      expect.objectContaining({
        phase: "editing",
        description: "孙悟空，但还没选作品",
        personaId: expect.any(String),
        draftId: expect.any(String),
      }),
    );
    expect(
      screen.getByRole("button", { name: "actions.next" }),
    ).toBeDisabled();
  });

  it("allows continuing with a preset after returning from custom persona creation", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterPersonaStep(user);
    await user.click(screen.getByTestId("persona-create-custom"));
    await user.type(
      screen.getByTestId("persona-custom-description"),
      "a draft worth keeping",
    );
    expect(
      screen.getByRole("button", { name: "actions.next" }),
    ).toBeDisabled();

    await user.click(screen.getByTestId("persona-back-to-picker"));
    await user.click(screen.getByTestId("persona-pick-ember"));

    expect(screen.getByTestId("persona-pick-ember")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(
      screen.getByRole("button", { name: "actions.next" }),
    ).toBeEnabled();
  });

  it("reuses one custom persona id when activation fails and the user retries", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      CUSTOM_PERSONA_ID,
    );
    const generated = generatedPersonaConfig();
    vi.spyOn(personasApi, "generateWithProgress").mockResolvedValue({
      success: true,
      message: "ok",
      data: generated,
      stages: [],
    } as any);
    const slug = `onboarding-custom-${CUSTOM_PERSONA_ID}`;
    const createSpy = vi.spyOn(personasApi, "create").mockResolvedValue({
      success: true,
      data: { persona_id: CUSTOM_PERSONA_ID, name: "Sage", slug },
    } as any);
    vi.mocked(personasApi.setActive)
      .mockRejectedValueOnce(new Error("activation unavailable"))
      .mockResolvedValueOnce({ success: true, persona_id: CUSTOM_PERSONA_ID });

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await enterPersonaStep(user);
    await user.click(screen.getByTestId("persona-create-custom"));
    await user.type(
      screen.getByTestId("persona-custom-description"),
      "a wise mentor",
    );
    await user.click(screen.getByTestId("persona-custom-generate"));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "actions.next" }),
      ).toBeEnabled(),
    );

    await user.click(screen.getByRole("button", { name: "actions.next" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "messages.personaActivationFailed",
    );
    await user.click(screen.getByRole("button", { name: "actions.next" }));
    await screen.findByText("firstContext.title");

    expect(createSpy).toHaveBeenCalledTimes(2);
    expect(createSpy.mock.calls.map(([payload]) => payload.persona_id)).toEqual(
      [CUSTOM_PERSONA_ID, CUSTOM_PERSONA_ID],
    );
    expect(createSpy.mock.calls.map(([payload]) => payload.slug)).toEqual([
      slug,
      slug,
    ]);
    expect(personasApi.setActive).toHaveBeenCalledTimes(2);
    expect(configApi.updateOnboardingDraft).toHaveBeenCalledTimes(1);
  });

  it("reuses the saved persona id when submitting a restored custom draft", async () => {
    const user = userEvent.setup();
    const slug = `onboarding-custom-${CUSTOM_PERSONA_ID}`;
    const restoredConfig = generatedPersonaConfig();
    localStorageMock.getItem.mockImplementation((key: string) => {
      if (key !== "magi_onboarding_state") return null;
      return JSON.stringify({
        version: 1,
        current: 2,
        values: DEFAULT_SYSTEM_CONFIG,
        seedSlug: slug,
        customPersonas: [
          {
            personaId: CUSTOM_PERSONA_ID,
            slug,
            name: "Sage",
            description: "wise mentor",
            config: restoredConfig,
          },
        ],
      });
    });
    const createSpy = vi.spyOn(personasApi, "create").mockResolvedValue({
      success: true,
      data: { persona_id: CUSTOM_PERSONA_ID, name: "Sage", slug },
    } as any);

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    await user.click(screen.getByRole("button", { name: "actions.next" }));
    expect(
      await screen.findByRole("button", { name: /Sage/i }),
    ).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "actions.next" }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    expect(createSpy).toHaveBeenCalledWith(
      expect.objectContaining({ persona_id: CUSTOM_PERSONA_ID, slug }),
    );
    expect(personasApi.setActive).toHaveBeenCalledWith(CUSTOM_PERSONA_ID);
    await screen.findByText("firstContext.title");
  });

  it("disables the footer Next button while a custom persona is generating", async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue(null);
    let resolveGen: (value: any) => void = () => {};
    vi.spyOn(personasApi, "generateWithProgress").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGen = resolve;
        }),
    );

    render(<OnboardingFlow initialConfig={DEFAULT_SYSTEM_CONFIG} />);

    await user.click(
      screen.getByRole("button", { name: /welcome\.getStarted/ }),
    );
    await user.click(await screen.findByTestId("llm-setup-provider-openai"));
    await user.type(screen.getByTestId("llm-setup-api-key"), "sk-test");
    const nextBtn = screen.getByRole("button", { name: "actions.next" });
    await waitFor(() => expect(nextBtn).toBeEnabled());
    await user.click(nextBtn);

    // Start a generation on the persona step.
    await user.click(await screen.findByTestId("persona-create-custom"));
    await user.type(
      screen.getByTestId("persona-custom-description"),
      "a wise mentor",
    );
    await user.click(screen.getByTestId("persona-custom-generate"));

    // Footer Next is disabled while the generation is in flight...
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "actions.next" }),
      ).toBeDisabled(),
    );
    await user.click(screen.getByTestId("persona-back-to-picker"));
    await user.click(screen.getByTestId("persona-pick-ember"));
    expect(
      screen.getByRole("button", { name: "actions.next" }),
    ).toBeDisabled();

    // ...and re-enabled once it resolves.
    resolveGen({
      success: true,
      message: "ok",
      data: {
        name: "Sage",
        avatar: "",
        description: "wise",
        appearance_prompt: "",
        identity_core: {
          identity_statement: "patient",
          values_loved: [],
          values_rejected: [],
          attention_biases: [],
        },
        idiolect: {
          sentence_style: "calm",
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
      },
      stages: [],
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "actions.next" }),
      ).toBeEnabled(),
    );
  });
});
