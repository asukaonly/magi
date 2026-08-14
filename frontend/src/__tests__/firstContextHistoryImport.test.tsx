import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  confirmMock,
  deleteMock,
  getMock,
  getRegistryMock,
  getSourcePreviewMock,
  listImportersMock,
  openExternalUrlMock,
  pickDirectoryMock,
  pickHistoryImportFilesMock,
  pickMarkdownFilesMock,
  previewImporterMock,
  previewMock,
  resumeMock,
  updateSelectionMock,
} = vi.hoisted(() => ({
  confirmMock: vi.fn(),
  deleteMock: vi.fn(),
  getMock: vi.fn(),
  getRegistryMock: vi.fn(),
  getSourcePreviewMock: vi.fn(),
  listImportersMock: vi.fn(),
  openExternalUrlMock: vi.fn(),
  pickDirectoryMock: vi.fn(),
  pickHistoryImportFilesMock: vi.fn(),
  pickMarkdownFilesMock: vi.fn(),
  previewImporterMock: vi.fn(),
  previewMock: vi.fn(),
  resumeMock: vi.fn(),
  updateSelectionMock: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: {
      language: "zh-CN",
      resolvedLanguage: "zh-CN",
    },
  }),
}));

vi.mock("@/runtime/desktop", () => ({
  openExternalUrl: (...args: unknown[]) => openExternalUrlMock(...args),
  pickDirectory: (...args: unknown[]) => pickDirectoryMock(...args),
  pickHistoryImportFiles: (...args: unknown[]) => pickHistoryImportFilesMock(...args),
  pickMarkdownFiles: (...args: unknown[]) => pickMarkdownFilesMock(...args),
}));

vi.mock("@/api/modules/historyImports", () => ({
  historyImportsApi: {
    previewMarkdown: (...args: unknown[]) => previewMock(...args),
    previewWithImporter: (...args: unknown[]) => previewImporterMock(...args),
    listImporters: (...args: unknown[]) => listImportersMock(...args),
    get: (...args: unknown[]) => getMock(...args),
    getSourcePreview: (...args: unknown[]) => getSourcePreviewMock(...args),
    confirm: (...args: unknown[]) => confirmMock(...args),
    resume: (...args: unknown[]) => resumeMock(...args),
    delete: (...args: unknown[]) => deleteMock(...args),
    updateSelection: (...args: unknown[]) => updateSelectionMock(...args),
  },
}));

vi.mock("@/api/modules/plugins", () => ({
  pluginsApi: {
    getRegistry: (...args: unknown[]) => getRegistryMock(...args),
  },
}));

import HistoryImportFlow from "@/components/history-imports/HistoryImportFlow";
import type { HistoryImportJob } from "@/api/modules/historyImports";
import { usePluginInstallPanelStore } from "@/stores/pluginInstallPanel";

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function documentPreview(): HistoryImportJob {
  return {
    job_id: "him-1",
    source_type: "markdown",
    importer_plugin_id: null,
    importer_id: null,
    source_ids: ["notes.md"],
    included_source_ids: ["notes.md"],
    detected_kind: "document",
    status: "preview_ready",
    total_records: 1,
    meaningful_records: 1,
    quick_target_records: 200,
    quick_max_records: 500,
    quick_imported_count: 0,
    imported_count: 0,
    projected_count: 0,
    self_participant_ids: [],
    warning_summary: {
      total_count: 0,
      codes: [],
      truncated: false,
    },
    quick_ready: false,
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
        sample: "# Notes\n\nMe: I started learning pottery.",
      },
    ],
    sources: [
      {
        source_id: "notes.md",
        source_name: "notes.md",
        detected_kind: "document",
        record_count: 1,
        meaningful_count: 1,
        first_event_at: 1_800_000_000,
        last_event_at: 1_800_000_000,
        timestamp_confidence: "file_mtime",
        sample: "# Notes\n\nMe: I started learning pottery.",
        included: true,
      },
    ],
    preview_records: [
      {
        source_id: "notes.md",
        source_name: "notes.md",
        session_id: "session-1",
        session_seq: 0,
        speaker_id: "__document_author__",
        speaker_name: "__document_author__",
        is_document_author: true,
        content: "# Notes\n\nMe: I started learning pottery.\n\nAlice: What do you like about it?",
        event_at: 1_800_000_000,
        timestamp_confidence: "file_mtime",
      },
    ],
  };
}

function readyJob(): HistoryImportJob {
  return {
    ...documentPreview(),
    status: "ready",
    quick_imported_count: 1,
    imported_count: 1,
    self_participant_ids: ["__document_author__"],
    quick_ready: true,
  };
}

function conversationPreview(): HistoryImportJob {
  return {
    ...documentPreview(),
    job_id: "him-chatgpt",
    source_type: "chatgpt_export",
    importer_plugin_id: "chatgpt-history",
    importer_id: "chatgpt_export",
    source_ids: ["conversation-1"],
    included_source_ids: ["conversation-1"],
    detected_kind: "chat",
    total_records: 3,
    meaningful_records: 3,
    participants: [
      {
        participant_id: "user",
        display_name: "You",
        is_document_author: false,
        message_count: 2,
        meaningful_count: 2,
        sample: "I have been learning pottery.",
      },
      {
        participant_id: "assistant",
        display_name: "ChatGPT",
        is_document_author: false,
        message_count: 1,
        meaningful_count: 1,
        sample: "What have you enjoyed about it?",
      },
    ],
    sources: [
      {
        source_id: "conversation-1",
        source_name: "Learning pottery",
        detected_kind: "chat",
        record_count: 3,
        meaningful_count: 3,
        first_event_at: 1_800_000_000,
        last_event_at: 1_800_000_100,
        timestamp_confidence: "exact",
        sample: "I have been learning pottery.",
        included: true,
      },
    ],
    preview_records: [
      {
        source_id: "conversation-1",
        source_name: "Learning pottery",
        session_id: "conversation-1",
        session_seq: 0,
        speaker_id: "user",
        speaker_name: "You",
        is_document_author: false,
        content: "I have been learning pottery.",
        event_at: 1_800_000_000,
        timestamp_confidence: "exact",
      },
    ],
  };
}

describe("FirstContextHistoryImport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pickMarkdownFilesMock.mockResolvedValue(["/tmp/notes.md"]);
    pickHistoryImportFilesMock.mockResolvedValue([]);
    pickDirectoryMock.mockResolvedValue(undefined);
    openExternalUrlMock.mockResolvedValue(undefined);
    listImportersMock.mockResolvedValue([]);
    getRegistryMock.mockResolvedValue({
      plugins: [],
      registry_version: "4",
      install_fingerprint: "registry-fingerprint",
    });
    usePluginInstallPanelStore.getState().closePanel();
    previewMock.mockResolvedValue(documentPreview());
    confirmMock.mockResolvedValue(readyJob());
    getMock.mockResolvedValue(readyJob());
    getSourcePreviewMock.mockResolvedValue({
      source_id: "notes.md",
      source_name: "notes.md",
      detected_kind: "document",
      records: documentPreview().preview_records,
      truncated: false,
    });
    deleteMock.mockResolvedValue(undefined);
    resumeMock.mockResolvedValue({
      ...readyJob(),
      status: "running",
    });
    updateSelectionMock.mockImplementation(
      async (_jobId: string, includedSourceIds: string[]) => ({
        ...documentPreview(),
        included_source_ids: includedSourceIds,
        sources: documentPreview().sources.map((source) => ({
          ...source,
          included: includedSourceIds.includes(source.source_id),
        })),
      }),
    );
  });

  it("previews Markdown as personal writing and reaches quick-ready", async () => {
    const user = userEvent.setup();
    const onJobUpdate = vi.fn();
    render(
      <HistoryImportFlow onJobUpdate={onJobUpdate} />,
    );

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.picker.files",
      }),
    );
    expect(await screen.findByTestId("history-import-preview")).toBeInTheDocument();
    const sourceList = screen.getByTestId("history-import-source-list");
    expect(sourceList).not.toHaveClass("max-h-[360px]");
    expect(sourceList).not.toHaveClass("overflow-y-auto");
    expect(previewMock).toHaveBeenCalledWith(["/tmp/notes.md"]);
    expect(
      screen.getByRole("button", {
        name: "firstContext.history.preview.previewFile",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("firstContext.history.preview.meaningfulRecords"),
    ).not.toBeInTheDocument();

    const sourceCheckbox = screen.getByRole("checkbox", {
      name: "firstContext.history.preview.includeFile",
    });
    expect(sourceCheckbox).toBeChecked();
    expect(
      screen.queryByText("firstContext.history.identity.title"),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.preview.confirm",
      }),
    );
    expect(confirmMock).toHaveBeenCalledWith("him-1", {
      confirmPersonalWriting: true,
      includedSourceIds: ["notes.md"],
      selfParticipantIds: [],
    });
    expect(await screen.findByTestId("history-import-ready")).toBeInTheDocument();
    expect(onJobUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        job_id: "him-1",
        quick_ready: true,
        quick_imported_count: 1,
      }),
    );
  });

  it("imports a platform export only after conversation and identity review", async () => {
    const user = userEvent.setup();
    listImportersMock.mockResolvedValue([
      {
        plugin_id: "chatgpt-history",
        importer_id: "chatgpt_export",
        display_name: "ChatGPT",
        display_name_i18n: { "zh-CN": "ChatGPT 历史" },
        description: "Import conversations from an official ChatGPT export.",
        description_i18n: { "zh-CN": "导入官方对话记录。" },
        accepted_extensions: ["zip", "json"],
        export_help_url: "https://example.com/export",
      },
    ]);
    pickHistoryImportFilesMock.mockResolvedValue(["/tmp/chatgpt-export.zip"]);
    previewImporterMock.mockResolvedValue(conversationPreview());
    confirmMock.mockResolvedValue({
      ...conversationPreview(),
      status: "ready",
      quick_ready: true,
      quick_imported_count: 2,
      imported_count: 2,
      self_participant_ids: ["user"],
    });

    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);

    expect(await screen.findByText("ChatGPT 历史")).toBeInTheDocument();
    expect(screen.getByText("导入官方对话记录。")).toBeInTheDocument();
    expect(screen.queryByText("ChatGPT")).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.platform.choose",
      }),
    );

    expect(pickHistoryImportFilesMock).toHaveBeenCalledWith(
      ["zip", "json"],
      "firstContext.history.platform.fileFilter",
    );
    expect(previewImporterMock).toHaveBeenCalledWith({
      pluginId: "chatgpt-history",
      importerId: "chatgpt_export",
      paths: ["/tmp/chatgpt-export.zip"],
    });
    expect(
      await screen.findByText("firstContext.history.identity.title"),
    ).toBeInTheDocument();
    const confirm = screen.getByRole("button", {
      name: "firstContext.history.preview.confirm",
    });
    expect(confirm).toBeDisabled();

    await user.click(screen.getByRole("checkbox", { name: /You/ }));
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    expect(confirmMock).toHaveBeenCalledWith("him-chatgpt", {
      confirmPersonalWriting: false,
      includedSourceIds: ["conversation-1"],
      selfParticipantIds: ["user"],
    });
  });

  it("summarizes omitted platform content without exposing warning details", async () => {
    const user = userEvent.setup();
    listImportersMock.mockResolvedValue([
      {
        plugin_id: "chatgpt-history",
        importer_id: "chatgpt_export",
        display_name: "ChatGPT",
        display_name_i18n: {},
        description: "Import conversations from an official export.",
        description_i18n: {},
        accepted_extensions: ["zip", "json"],
        export_help_url: null,
      },
    ]);
    pickHistoryImportFilesMock.mockResolvedValue(["/tmp/chatgpt-export.zip"]);
    previewImporterMock.mockResolvedValue({
      ...conversationPreview(),
      warning_summary: {
        total_count: 3,
        codes: ["attachment_skipped", "unsupported_message"],
        truncated: true,
      },
    });

    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);
    await user.click(
      await screen.findByRole("button", {
        name: "firstContext.history.platform.choose",
      }),
    );

    expect(
      await screen.findByText(
        "firstContext.history.preview.omittedContentNotice",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("attachment_skipped")).not.toBeInTheDocument();
    expect(screen.queryByText("unsupported_message")).not.toBeInTheDocument();
  });

  it("clears a hidden identity when its conversation leaves the selection", async () => {
    const user = userEvent.setup();
    listImportersMock.mockResolvedValue([
      {
        plugin_id: "chatgpt-history",
        importer_id: "chatgpt_export",
        display_name: "ChatGPT",
        display_name_i18n: {},
        description: "Import conversations from an official export.",
        description_i18n: {},
        accepted_extensions: ["zip", "json"],
        export_help_url: null,
      },
    ]);
    pickHistoryImportFilesMock.mockResolvedValue(["/tmp/chatgpt-export.zip"]);
    previewImporterMock.mockResolvedValue(conversationPreview());
    updateSelectionMock.mockImplementation(
      async (_jobId: string, includedSourceIds: string[]) => ({
        ...conversationPreview(),
        included_source_ids: includedSourceIds,
        participants: includedSourceIds.length > 0
          ? conversationPreview().participants
          : [],
        sources: conversationPreview().sources.map((source) => ({
          ...source,
          included: includedSourceIds.includes(source.source_id),
        })),
      }),
    );

    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);
    await user.click(
      await screen.findByRole("button", {
        name: "firstContext.history.platform.choose",
      }),
    );
    await user.click(await screen.findByRole("checkbox", { name: /You/ }));

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.preview.invertSelection",
      }),
    );
    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.preview.selectAll",
      }),
    );

    expect(await screen.findByRole("checkbox", { name: /You/ })).not.toBeChecked();
    expect(
      screen.getByRole("button", {
        name: "firstContext.history.preview.confirm",
      }),
    ).toBeDisabled();
  });

  it.each([
    [
      "unknown",
      "firstContext.history.preview.missingTime",
      "firstContext.history.sourcePreview.timeMissing",
    ],
    [
      "inferred",
      "firstContext.history.preview.approximateTime",
      "firstContext.history.sourcePreview.timeApproximate",
    ],
  ])(
    "does not present %s conversation timestamps as exact time",
    async (timestampConfidence, sourceTimeLabel, recordTimeLabel) => {
      const user = userEvent.setup();
      listImportersMock.mockResolvedValue([
        {
          plugin_id: "chatgpt-history",
          importer_id: "chatgpt_export",
          display_name: "ChatGPT",
          display_name_i18n: {},
          description: "Import conversations from an official export.",
          description_i18n: {},
          accepted_extensions: ["zip", "json"],
          export_help_url: null,
        },
      ]);
      const nonExactTimeJob = conversationPreview();
      nonExactTimeJob.sources = nonExactTimeJob.sources.map((source) => ({
        ...source,
        first_event_at: 0,
        last_event_at: 0,
        timestamp_confidence: timestampConfidence,
      }));
      nonExactTimeJob.preview_records = nonExactTimeJob.preview_records.map(
        (record) => ({
          ...record,
          event_at: 0,
          timestamp_confidence: timestampConfidence,
        }),
      );
      pickHistoryImportFilesMock.mockResolvedValue(["/tmp/chatgpt-export.zip"]);
      previewImporterMock.mockResolvedValue(nonExactTimeJob);
      getSourcePreviewMock.mockResolvedValue({
        source_id: "conversation-1",
        source_name: "Learning pottery",
        detected_kind: "chat",
        records: nonExactTimeJob.preview_records,
        truncated: false,
      });

      render(<HistoryImportFlow onJobUpdate={vi.fn()} />);
      await user.click(
        await screen.findByRole("button", {
          name: "firstContext.history.platform.choose",
        }),
      );

      expect(await screen.findByText(sourceTimeLabel)).toBeInTheDocument();
      await user.click(
        screen.getByRole("button", {
          name: "firstContext.history.preview.previewFile",
        }),
      );
      expect(await screen.findByText(recordTimeLabel)).toBeInTheDocument();
      expect(screen.queryByText(/1970/)).not.toBeInTheDocument();
    },
  );

  it("offers an install action for an uninstalled platform importer", async () => {
    const user = userEvent.setup();
    getRegistryMock.mockResolvedValue({
      plugins: [
        {
          plugin_id: "chatgpt-history",
          name: "ChatGPT history",
          name_i18n: { "zh-CN": "ChatGPT 对话记录" },
          version: "0.1.0",
          description: "Import an official account export.",
          description_i18n: { "zh-CN": "导入官方账号导出文件。" },
          author: "Magi",
          icon: "lucide:messages-square",
          official: true,
          contribution_types: ["history_importer"],
          platforms: ["darwin", "windows", "linux"],
          min_sdk_version: "0.1.0",
          homepage: "",
          repository: "",
          path: "chatgpt-history",
          installed: false,
          installed_version: null,
          update_available: false,
          capabilities: [],
        },
        {
          plugin_id: "untrusted-history",
          name: "Untrusted history",
          name_i18n: {},
          version: "0.1.0",
          description: "Not eligible for onboarding installation.",
          description_i18n: {},
          author: "Unknown",
          official: false,
          contribution_types: ["history_importer"],
          platforms: ["darwin"],
          min_sdk_version: "0.1.0",
          homepage: "",
          repository: "",
          path: "untrusted-history",
          installed: false,
          installed_version: null,
          update_available: false,
          capabilities: [],
        },
      ],
      registry_version: "4",
      install_fingerprint: "registry-fingerprint",
    });

    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);

    expect(await screen.findByText("ChatGPT 对话记录")).toBeInTheDocument();
    expect(screen.queryByText("Untrusted history")).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.platform.install",
      }),
    );

    expect(usePluginInstallPanelStore.getState()).toMatchObject({
      open: true,
      pluginId: "chatgpt-history",
      installMode: true,
      context: "history_import",
    });
  });

  it("offers an enable action when an installed importer is not registered", async () => {
    const user = userEvent.setup();
    getRegistryMock.mockResolvedValue({
      plugins: [
        {
          plugin_id: "platform-history",
          name: "Platform history",
          name_i18n: {},
          version: "0.1.0",
          description: "Import an account export.",
          description_i18n: {},
          author: "Magi",
          icon: "lucide:messages-square",
          official: true,
          contribution_types: ["history_importer"],
          platforms: ["darwin", "windows", "linux"],
          min_sdk_version: "0.1.0",
          homepage: "",
          repository: "",
          path: "platform-history",
          installed: true,
          installed_version: "0.1.0",
          update_available: false,
          capabilities: [],
        },
      ],
      registry_version: "4",
      install_fingerprint: "registry-fingerprint",
    });

    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);

    await user.click(
      await screen.findByRole("button", {
        name: "firstContext.history.platform.enable",
      }),
    );

    expect(usePluginInstallPanelStore.getState()).toMatchObject({
      open: true,
      pluginId: "platform-history",
      installMode: false,
      context: "history_import",
    });
  });

  it("keeps the last progress visible and lets the user restart failed polling", async () => {
    const user = userEvent.setup();
    getMock
      .mockReset()
      .mockResolvedValueOnce(readyJob())
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue(readyJob());

    render(
      <HistoryImportFlow
        initialJobId="him-1"
        onJobUpdate={vi.fn()}
      />,
    );

    expect(await screen.findByTestId("history-import-ready")).toBeInTheDocument();
    expect(
      await screen.findByText("firstContext.history.ready.progressUnavailable", {}, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(screen.getByText("firstContext.history.ready.title")).toBeInTheDocument();

    getMock.mockResolvedValueOnce({
      ...readyJob(),
      status: "completed",
      projected_count: 1,
    });
    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.ready.refreshProgress",
      }),
    );

    await waitFor(() => {
      expect(
        screen.queryByText("firstContext.history.ready.progressUnavailable"),
      ).not.toBeInTheDocument();
    });
    expect(getMock).toHaveBeenCalledTimes(3);
  });

  it("treats selecting a personal file as its authorship confirmation", async () => {
    const user = userEvent.setup();
    previewMock.mockResolvedValue({
      ...documentPreview(),
      detected_kind: "document",
      sources: [
        {
          ...documentPreview().sources[0],
          detected_kind: "document",
          timestamp_confidence: "file_mtime",
        },
      ],
      participants: [
        {
          participant_id: "__document_author__",
          display_name: "Document author",
          is_document_author: true,
          message_count: 1,
          meaningful_count: 1,
          sample: "A journal paragraph.",
        },
      ],
      preview_records: [
        {
          ...documentPreview().preview_records[0],
          is_document_author: true,
          speaker_name: "__document_author__",
          timestamp_confidence: "file_mtime",
        },
      ],
    } satisfies HistoryImportJob);

    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);
    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.picker.files",
      }),
    );
    const confirm = await screen.findByRole("button", {
      name: "firstContext.history.preview.confirm",
    });
    expect(confirm).toBeEnabled();
    expect(
      screen.getByText("firstContext.history.preview.approximateFileTime"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("firstContext.history.writing.title"),
    ).not.toBeInTheDocument();

    await user.click(confirm);
    expect(confirmMock).toHaveBeenCalledWith("him-1", {
      confirmPersonalWriting: true,
      includedSourceIds: ["notes.md"],
      selfParticipantIds: [],
    });
  });

  it("previews one file in a side panel", async () => {
    const user = userEvent.setup();
    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.picker.files",
      }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "firstContext.history.preview.previewFile",
      }),
    );

    expect(getSourcePreviewMock).toHaveBeenCalledWith(
      "him-1",
      "notes.md",
      expect.any(AbortSignal),
    );
    expect(
      await screen.findByText("Me: I started learning pottery."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("firstContext.history.sourcePreview.description"),
    ).toBeInTheDocument();
  });

  it("renders document previews as Markdown instead of raw text", async () => {
    const user = userEvent.setup();
    getSourcePreviewMock.mockResolvedValue({
      source_id: "notes.md",
      source_name: "notes.md",
      detected_kind: "document",
      records: [
        {
          ...documentPreview().preview_records[0],
          speaker_name: "__document_author__",
          is_document_author: true,
          content: "# 周末记录\n\n- 去了书店\n- 听了一张专辑",
        },
      ],
      truncated: false,
    });
    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.picker.files",
      }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "firstContext.history.preview.previewFile",
      }),
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "周末记录" }),
    ).toBeInTheDocument();
    expect(screen.getByText("去了书店").tagName).toBe("LI");
    expect(screen.queryByText("# 周末记录")).not.toBeInTheDocument();
  });

  it("supports inverting the file selection to an empty set", async () => {
    const user = userEvent.setup();
    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.picker.files",
      }),
    );
    const confirm = await screen.findByRole("button", {
      name: "firstContext.history.preview.confirm",
    });
    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.preview.invertSelection",
      }),
    );

    await waitFor(() =>
      expect(updateSelectionMock).toHaveBeenCalledWith("him-1", []),
    );
    expect(confirm).toBeDisabled();
  });

  it("deletes the preview before choosing different files", async () => {
    const user = userEvent.setup();
    const onJobUpdate = vi.fn();
    render(<HistoryImportFlow onJobUpdate={onJobUpdate} />);

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.picker.files",
      }),
    );
    await screen.findByTestId("history-import-preview");

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.preview.chooseAgain",
      }),
    );

    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith("him-1"));
    expect(screen.getByTestId("history-import-empty")).toBeInTheDocument();
    expect(onJobUpdate).toHaveBeenLastCalledWith(null);
  });

  it("shows and retries a completed import with a memory handoff gap", async () => {
    const user = userEvent.setup();
    const partialJob = {
      ...readyJob(),
      status: "completed" as const,
      projected_count: 0,
    };
    getMock.mockResolvedValue(partialJob);
    render(
      <HistoryImportFlow
        initialJobId="him-1"
        onJobUpdate={vi.fn()}
      />,
    );

    expect(await screen.findByTestId("history-import-ready")).toBeInTheDocument();
    expect(
      screen.getByText("firstContext.history.ready.partial"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("firstContext.history.ready.memoryQueued"),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.ready.retry",
      }),
    );
    await waitFor(() => expect(resumeMock).toHaveBeenCalledWith("him-1"));
  });

  it("ignores an older source preview after the drawer closes and another source opens", async () => {
    const user = userEvent.setup();
    const firstPreview = deferred<{
      source_id: string;
      source_name: string;
      detected_kind: "document";
      records: HistoryImportJob["preview_records"];
      truncated: boolean;
    }>();
    const secondPreview = deferred<{
      source_id: string;
      source_name: string;
      detected_kind: "document";
      records: HistoryImportJob["preview_records"];
      truncated: boolean;
    }>();
    const secondSource = {
      ...documentPreview().sources[0],
      source_id: "second.md",
      source_name: "second.md",
    };
    previewMock.mockResolvedValue({
      ...documentPreview(),
      source_ids: ["notes.md", "second.md"],
      included_source_ids: ["notes.md", "second.md"],
      sources: [documentPreview().sources[0], secondSource],
    });
    getSourcePreviewMock.mockImplementation(
      (_jobId: string, sourceId: string) =>
        sourceId === "notes.md" ? firstPreview.promise : secondPreview.promise,
    );

    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);
    await user.click(
      screen.getByRole("button", { name: "firstContext.history.picker.files" }),
    );
    const previewButtons = await screen.findAllByRole("button", {
      name: "firstContext.history.preview.previewFile",
    });
    await user.click(previewButtons[0]);
    const firstSignal = getSourcePreviewMock.mock.calls[0]?.[2] as AbortSignal;
    await user.click(
      screen.getByRole("button", { name: "firstContext.history.sourcePreview.close" }),
    );
    expect(firstSignal.aborted).toBe(true);

    await user.click(previewButtons[1]);
    secondPreview.resolve({
      source_id: "second.md",
      source_name: "second.md",
      detected_kind: "document",
      records: [{
        ...documentPreview().preview_records[0],
        source_id: "second.md",
        source_name: "second.md",
        content: "Second preview content",
      }],
      truncated: false,
    });
    expect(await screen.findByText("Second preview content")).toBeInTheDocument();

    firstPreview.resolve({
      source_id: "notes.md",
      source_name: "notes.md",
      detected_kind: "document",
      records: [{
        ...documentPreview().preview_records[0],
        content: "Stale first preview content",
      }],
      truncated: false,
    });
    await waitFor(() => {
      expect(screen.queryByText("Stale first preview content")).not.toBeInTheDocument();
    });
    expect(screen.getAllByText("second.md").length).toBeGreaterThan(0);
  });

  it("keeps choose-again locked until a selection update settles", async () => {
    const user = userEvent.setup();
    const selection = deferred<HistoryImportJob>();
    updateSelectionMock.mockReturnValue(selection.promise);
    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);

    await user.click(
      screen.getByRole("button", { name: "firstContext.history.picker.files" }),
    );
    await user.click(
      await screen.findByRole("button", {
        name: "firstContext.history.preview.invertSelection",
      }),
    );
    const chooseAgainButton = screen.getByRole("button", {
      name: "firstContext.history.preview.chooseAgain",
    });
    expect(chooseAgainButton).toBeDisabled();
    expect(deleteMock).not.toHaveBeenCalled();

    selection.resolve({
      ...documentPreview(),
      included_source_ids: [],
      sources: documentPreview().sources.map((source) => ({
        ...source,
        included: false,
      })),
    });
    await waitFor(() => expect(chooseAgainButton).toBeEnabled());
    await user.click(chooseAgainButton);
    expect(deleteMock).toHaveBeenCalledWith("him-1");
  });

  it("does not publish a preview job after the flow unmounts", async () => {
    const user = userEvent.setup();
    const preview = deferred<HistoryImportJob>();
    const onJobUpdate = vi.fn();
    previewMock.mockReturnValue(preview.promise);
    const { unmount } = render(
      <HistoryImportFlow onJobUpdate={onJobUpdate} />,
    );

    await user.click(
      screen.getByRole("button", { name: "firstContext.history.picker.files" }),
    );
    await waitFor(() => expect(previewMock).toHaveBeenCalled());
    unmount();
    preview.resolve(documentPreview());
    await Promise.resolve();
    await Promise.resolve();

    expect(onJobUpdate).not.toHaveBeenCalled();
  });

  it("shows a pre-quick failure and resumes it instead of confirming again", async () => {
    const user = userEvent.setup();
    const failedJob: HistoryImportJob = {
      ...documentPreview(),
      status: "failed",
      quick_ready: false,
      error_code: "history_importer_timeout",
    };
    getMock.mockResolvedValue(failedJob);
    resumeMock.mockResolvedValue({
      ...failedJob,
      status: "running",
    });

    render(
      <HistoryImportFlow initialJobId="him-1" onJobUpdate={vi.fn()} />,
    );

    expect(await screen.findByTestId("history-import-failed")).toBeInTheDocument();
    expect(
      screen.getByText("firstContext.history.errors.history_importer_timeout"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("firstContext.history.failed.errorCode"),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "firstContext.history.failed.retry" }),
    );
    expect(resumeMock).toHaveBeenCalledWith("him-1");
    expect(confirmMock).not.toHaveBeenCalled();
    expect(await screen.findByTestId("history-import-preparing")).toBeInTheDocument();
  });

  it("keeps a durable draft id when restoration fails and retries loading it", async () => {
    const user = userEvent.setup();
    getMock
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(documentPreview());
    const onJobUpdate = vi.fn();
    render(
      <HistoryImportFlow initialJobId="him-1" onJobUpdate={onJobUpdate} />,
    );

    expect(
      await screen.findByRole("button", {
        name: "firstContext.history.restoreRetry",
      }),
    ).toBeInTheDocument();
    expect(onJobUpdate).not.toHaveBeenCalledWith(null);
    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.restoreRetry",
      }),
    );
    expect(await screen.findByTestId("history-import-preview")).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledTimes(2);
  });

  it("localizes picker and export-help failures and leaves the actions retryable", async () => {
    const user = userEvent.setup();
    pickMarkdownFilesMock.mockRejectedValueOnce(new Error("dialog unavailable"));
    pickDirectoryMock.mockRejectedValueOnce(new Error("dialog unavailable"));
    listImportersMock.mockResolvedValue([
      {
        plugin_id: "platform-history",
        importer_id: "account-export",
        display_name: "Platform history",
        display_name_i18n: {},
        description: "Import an account export.",
        description_i18n: {},
        accepted_extensions: ["zip"],
        participant_identity_scope: "export",
        export_help_url: "https://example.com/export",
      },
    ]);
    openExternalUrlMock.mockRejectedValueOnce(new Error("cannot open"));
    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);

    const chooseFilesButton = screen.getByRole("button", {
      name: "firstContext.history.picker.files",
    });
    await user.click(chooseFilesButton);
    expect(
      await screen.findByText(
        "firstContext.history.errors.history_import_file_picker_failed",
      ),
    ).toBeInTheDocument();
    expect(chooseFilesButton).toBeEnabled();

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.picker.folder",
      }),
    );
    expect(
      await screen.findByText(
        "firstContext.history.errors.history_import_directory_picker_failed",
      ),
    ).toBeInTheDocument();

    await user.click(
      await screen.findByRole("button", {
        name: "firstContext.history.platform.help",
      }),
    );
    expect(
      await screen.findByText(
        "firstContext.history.errors.history_import_export_help_failed",
      ),
    ).toBeInTheDocument();
  });

  it("paginates large source selections and exposes progress semantics", async () => {
    const user = userEvent.setup();
    const sources = Array.from({ length: 51 }, (_, index) => ({
      ...documentPreview().sources[0],
      source_id: `note-${index}.md`,
      source_name: `note-${index}.md`,
    }));
    previewMock.mockResolvedValue({
      ...documentPreview(),
      source_ids: sources.map((source) => source.source_id),
      included_source_ids: sources.map((source) => source.source_id),
      sources,
    });
    render(<HistoryImportFlow onJobUpdate={vi.fn()} />);

    await user.click(
      screen.getByRole("button", { name: "firstContext.history.picker.files" }),
    );
    expect(await screen.findAllByRole("checkbox")).toHaveLength(50);
    expect(screen.getByText("note-0.md")).toBeInTheDocument();
    expect(screen.queryByText("note-50.md")).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "firstContext.history.preview.nextPage" }),
    );
    expect(await screen.findByText("note-50.md")).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(1);

    getMock.mockResolvedValue({ ...readyJob(), job_id: "him-ready" });
    const { rerender } = render(
      <HistoryImportFlow initialJobId="him-ready" onJobUpdate={vi.fn()} />,
    );
    expect(await screen.findByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
    rerender(<div />);
  });
});
