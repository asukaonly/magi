import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  deleteMock,
  listMock,
  resumeMock,
} = vi.hoisted(() => ({
  deleteMock: vi.fn(),
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
    get: vi.fn(),
    previewMarkdown: vi.fn(),
    updateSelection: vi.fn(),
    confirm: vi.fn(),
  },
}));

vi.mock("@/runtime/desktop", () => ({
  pickDirectory: vi.fn(),
  pickMarkdownFiles: vi.fn(),
}));

import type { HistoryImportJob } from "@/api/modules/historyImports";
import HistoryImportsSection from "@/components/history-imports/HistoryImportsSection";
import { historyImportProgress } from "@/components/history-imports/historyImportProgress";

function completedJob(): HistoryImportJob {
  return {
    job_id: "him-1",
    source_type: "markdown",
    source_files: ["journal/2026-07-01.md", "notes.md"],
    included_files: ["journal/2026-07-01.md", "notes.md"],
    detected_kind: "document",
    status: "completed",
    total_records: 12,
    meaningful_records: 10,
    quick_target_records: 200,
    quick_max_records: 500,
    quick_imported_count: 12,
    imported_count: 12,
    projected_count: 12,
    self_participants: ["__document_author__"],
    warnings: [],
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
    resumeMock.mockResolvedValue({
      ...completedJob(),
      status: "running",
    });
  });

  it("shows durable imports and deletes a whole batch after confirmation", async () => {
    const user = userEvent.setup();
    render(<HistoryImportsSection />);

    expect(
      await screen.findByText("journal/2026-07-01.md +1"),
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
      screen.queryByText("journal/2026-07-01.md +1"),
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
      screen.getByText("memory.sourcesPage.historyImports.memoryQueued"),
    ).toBeInTheDocument();
    expect(historyImportProgress(partialJob)).toMatchObject({
      savedCount: 12,
      queuedCount: 8,
      savedPercent: 100,
      hasMemoryQueueGap: true,
      fullyTransferred: false,
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
      screen.getByText(
        "firstContext.history.picker.scenarios.journal.title",
      ),
    ).toBeInTheDocument();
  });

  it("reports whether any history imports are available", async () => {
    const onAvailabilityChange = vi.fn();
    render(
      <HistoryImportsSection onAvailabilityChange={onAvailabilityChange} />,
    );

    await screen.findByText("journal/2026-07-01.md +1");
    expect(onAvailabilityChange).toHaveBeenCalledWith("loading");
    expect(onAvailabilityChange).toHaveBeenCalledWith("available");
  });
});
