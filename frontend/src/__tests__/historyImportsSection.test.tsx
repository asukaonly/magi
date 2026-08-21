import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  deleteMock,
  getMock,
  listMock,
  resumeMock,
} = vi.hoisted(() => ({
  deleteMock: vi.fn(),
  getMock: vi.fn(),
  listMock: vi.fn(),
  resumeMock: vi.fn(),
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

vi.mock("@/api/modules/historyImports", () => ({
  historyImportsApi: {
    list: (...args: unknown[]) => listMock(...args),
    delete: (...args: unknown[]) => deleteMock(...args),
    resume: (...args: unknown[]) => resumeMock(...args),
    get: (...args: unknown[]) => getMock(...args),
    getSourcePreview: vi.fn(),
    listImporters: vi.fn().mockResolvedValue([]),
    previewMarkdown: vi.fn(),
    previewWithImporter: vi.fn(),
    updateSelection: vi.fn(),
    confirm: vi.fn(),
  },
}));

vi.mock("@/api/modules/plugins", () => ({
  pluginsApi: {
    getRegistry: vi.fn().mockResolvedValue({
      plugins: [],
      registry_version: "4",
      install_fingerprint: "registry-fingerprint",
    }),
  },
}));

vi.mock("@/runtime/desktop", () => ({
  openExternalUrl: vi.fn(),
  pickDirectory: vi.fn(),
  pickHistoryImportFiles: vi.fn(),
  pickMarkdownFiles: vi.fn(),
}));

import type { HistoryImportJob } from "@/api/modules/historyImports";
import HistoryImportsSection from "@/components/history-imports/HistoryImportsSection";
import {
  historyImportProgress,
  historyImportStages,
} from "@/components/history-imports/historyImportProgress";

function completedJob(): HistoryImportJob {
  return {
    job_id: "him-1",
    source_type: "markdown",
    importer_plugin_id: null,
    importer_id: null,
    source_ids: ["journal/2026-07-01.md", "notes.md"],
    included_source_ids: ["journal/2026-07-01.md", "notes.md"],
    detected_kind: "document",
    status: "completed",
    total_records: 12,
    meaningful_records: 10,
    quick_target_records: 200,
    quick_max_records: 500,
    quick_imported_count: 12,
    imported_count: 12,
    projected_count: 12,
    self_participant_ids: ["__document_author__"],
    warning_summary: {
      total_count: 0,
      codes: [],
      truncated: false,
    },
    quick_ready: true,
    error_code: null,
    created_at: 1_800_000_000,
    updated_at: 1_800_000_100,
    participants: [],
    sources: [],
    preview_records: [],
  };
}

describe("HistoryImportsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listMock.mockResolvedValue([completedJob()]);
    deleteMock.mockResolvedValue(undefined);
    getMock.mockResolvedValue(completedJob());
    resumeMock.mockResolvedValue({
      ...completedJob(),
      status: "running",
    });
  });

  it("shows durable imports and deletes a whole batch after confirmation", async () => {
    const user = userEvent.setup();
    render(<HistoryImportsSection />);

    expect(
      await screen.findByText("memory.sourcesPage.historyImports.personalWritingBatch"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("memory.sourcesPage.historyImports.fileCount"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("memory.sourcesPage.historyImports.recordCount"),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", {
        name: "memory.sourcesPage.historyImports.deleteAction",
      }),
    );
    expect(
      screen.getByText("memory.sourcesPage.historyImports.deleteTitle"),
    ).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: "memory.sourcesPage.historyImports.deleteConfirm",
      }),
    );

    await waitFor(() => expect(deleteMock).toHaveBeenCalledWith("him-1"));
    expect(
      screen.queryByText("memory.sourcesPage.historyImports.personalWritingBatch"),
    ).not.toBeInTheDocument();
  });

  it("distinguishes saved source text from memory-queue handoff", async () => {
    const user = userEvent.setup();
    const partialJob = {
      ...completedJob(),
      projected_count: 8,
    };
    listMock.mockResolvedValue([partialJob]);
    render(<HistoryImportsSection />);

    expect(
      await screen.findByText("memory.sourcesPage.historyImports.status.partial"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("memory.sourcesPage.historyImports.status.completed"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("memory.sourcesPage.historyImports.stages.source.saved"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("memory.sourcesPage.historyImports.stages.memoryHandoff.paused"),
    ).toBeInTheDocument();
    expect(historyImportProgress(partialJob)).toMatchObject({
      savedCount: 12,
      queuedCount: 8,
      hasMemoryQueueGap: true,
      fullyTransferred: false,
    });
    expect(historyImportStages(partialJob)).toEqual({
      source: "saved",
      memoryHandoff: "paused",
    });

    await user.click(
      screen.getByRole("button", {
        name: "memory.sourcesPage.historyImports.continue",
      }),
    );
    await waitFor(() => expect(resumeMock).toHaveBeenCalledWith("him-1"));
  });

  it("opens the same guided import flow outside onboarding", async () => {
    const user = userEvent.setup();
    listMock.mockResolvedValue([]);
    render(<HistoryImportsSection />);

    await screen.findByText("memory.sourcesPage.historyImports.empty");
    await user.click(
      screen.getByRole("button", {
        name: "memory.sourcesPage.historyImports.add",
      }),
    );

    expect(screen.getByTestId("history-import-empty")).toBeInTheDocument();
    expect(
      screen.getByText("firstContext.history.picker.markdownTitle"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("firstContext.history.platform.empty"),
    ).toBeInTheDocument();
  });

  it("reports whether any history imports are available", async () => {
    const onAvailabilityChange = vi.fn();
    render(
      <HistoryImportsSection onAvailabilityChange={onAvailabilityChange} />,
    );

    await screen.findByText("memory.sourcesPage.historyImports.personalWritingBatch");
    expect(onAvailabilityChange).toHaveBeenCalledWith("loading");
    expect(onAvailabilityChange).toHaveBeenCalledWith("available");
  });

  it("labels lightweight platform jobs without hydrated source summaries", async () => {
    listMock.mockResolvedValue([
      {
        ...completedJob(),
        source_type: "platform_chat",
        detected_kind: "chat",
        importer_plugin_id: "platform-history",
        importer_id: "account-export",
      },
    ]);

    render(<HistoryImportsSection />);

    expect(
      await screen.findByText("memory.sourcesPage.historyImports.platformBatch"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("memory.sourcesPage.historyImports.untitled"),
    ).not.toBeInTheDocument();
  });

  it("keeps the last list visible and stops polling after a refresh error", async () => {
    const user = userEvent.setup();
    const runningJob = { ...completedJob(), status: "running" as const };
    listMock
      .mockReset()
      .mockResolvedValueOnce([runningJob])
      .mockRejectedValueOnce(new Error("offline"));

    render(<HistoryImportsSection />);

    expect(
      await screen.findByText("memory.sourcesPage.historyImports.personalWritingBatch"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        "memory.sourcesPage.historyImports.progressRefreshFailed",
        {},
        { timeout: 3000 },
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("memory.sourcesPage.historyImports.personalWritingBatch"),
    ).toBeInTheDocument();

    await new Promise((resolve) => window.setTimeout(resolve, 1700));
    expect(listMock).toHaveBeenCalledTimes(2);

    listMock.mockResolvedValueOnce([
      { ...runningJob, status: "completed", updated_at: runningJob.updated_at + 1 },
    ]);
    await user.click(
      screen.getByRole("button", {
        name: "memory.sourcesPage.historyImports.refreshProgress",
      }),
    );
    await waitFor(() => {
      expect(
        screen.queryByText("memory.sourcesPage.historyImports.progressRefreshFailed"),
      ).not.toBeInTheDocument();
    });
  });

  it("reopens a durable preview draft for confirmation after the flow is collapsed", async () => {
    const user = userEvent.setup();
    const draft = {
      ...completedJob(),
      status: "preview_ready" as const,
      quick_ready: false,
      quick_imported_count: 0,
      imported_count: 0,
      projected_count: 0,
      sources: [
        {
          source_id: "notes.md",
          source_name: "notes.md",
          detected_kind: "document" as const,
          record_count: 1,
          meaningful_count: 1,
          first_event_at: 1_800_000_000,
          last_event_at: 1_800_000_000,
          timestamp_confidence: "file_mtime",
          sample: "A note",
          included: true,
        },
      ],
      source_ids: ["notes.md"],
      included_source_ids: ["notes.md"],
    };
    listMock.mockResolvedValue([draft]);
    getMock.mockResolvedValue(draft);
    render(<HistoryImportsSection />);

    await user.click(
      await screen.findByRole("button", {
        name: "memory.sourcesPage.historyImports.review",
      }),
    );
    expect(getMock).toHaveBeenCalledWith("him-1");
    expect(await screen.findByTestId("history-import-preview")).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", {
        name: "memory.sourcesPage.historyImports.close",
      }),
    );
    expect(screen.queryByTestId("history-import-preview")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "memory.sourcesPage.historyImports.review",
      }),
    ).toBeInTheDocument();
  });
});
