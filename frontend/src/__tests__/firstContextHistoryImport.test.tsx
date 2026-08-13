import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  confirmMock,
  deleteMock,
  getMock,
  getSourcePreviewMock,
  openExternalUrlMock,
  pickDirectoryMock,
  pickMarkdownFilesMock,
  previewMock,
  resumeMock,
  updateSelectionMock,
} = vi.hoisted(() => ({
  confirmMock: vi.fn(),
  deleteMock: vi.fn(),
  getMock: vi.fn(),
  getSourcePreviewMock: vi.fn(),
  openExternalUrlMock: vi.fn(),
  pickDirectoryMock: vi.fn(),
  pickMarkdownFilesMock: vi.fn(),
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
  pickMarkdownFiles: (...args: unknown[]) => pickMarkdownFilesMock(...args),
}));

vi.mock("@/api/modules/historyImports", () => ({
  historyImportsApi: {
    previewMarkdown: (...args: unknown[]) => previewMock(...args),
    get: (...args: unknown[]) => getMock(...args),
    getSourcePreview: (...args: unknown[]) => getSourcePreviewMock(...args),
    confirm: (...args: unknown[]) => confirmMock(...args),
    resume: (...args: unknown[]) => resumeMock(...args),
    delete: (...args: unknown[]) => deleteMock(...args),
    updateSelection: (...args: unknown[]) => updateSelectionMock(...args),
  },
}));

import HistoryImportFlow from "@/components/history-imports/HistoryImportFlow";
import type { HistoryImportJob } from "@/api/modules/historyImports";

function documentPreview(): HistoryImportJob {
  return {
    job_id: "him-1",
    source_type: "markdown",
    source_files: ["notes.md"],
    included_files: ["notes.md"],
    detected_kind: "document",
    status: "preview_ready",
    total_records: 1,
    meaningful_records: 1,
    quick_target_records: 200,
    quick_max_records: 500,
    quick_imported_count: 0,
    imported_count: 0,
    projected_count: 0,
    self_participants: [],
    warnings: [],
    quick_ready: false,
    error_code: null,
    created_at: 1_800_000_000,
    updated_at: 1_800_000_000,
    participants: [
      {
        name: "__document_author__",
        is_document_author: true,
        message_count: 1,
        meaningful_count: 1,
        sample: "# Notes\n\nMe: I started learning pottery.",
      },
    ],
    sources: [
      {
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
        source_name: "notes.md",
        session_id: "session-1",
        session_seq: 0,
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
    self_participants: ["__document_author__"],
    quick_ready: true,
  };
}

describe("FirstContextHistoryImport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pickMarkdownFilesMock.mockResolvedValue(["/tmp/notes.md"]);
    pickDirectoryMock.mockResolvedValue(undefined);
    previewMock.mockResolvedValue(documentPreview());
    confirmMock.mockResolvedValue(readyJob());
    getMock.mockResolvedValue(readyJob());
    getSourcePreviewMock.mockResolvedValue({
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
      async (_jobId: string, includedFiles: string[]) => ({
        ...documentPreview(),
        included_files: includedFiles,
        sources: documentPreview().sources.map((source) => ({
          ...source,
          included: includedFiles.includes(source.source_name),
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
      includedFiles: ["notes.md"],
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
          name: "__document_author__",
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
      includedFiles: ["notes.md"],
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

    expect(getSourcePreviewMock).toHaveBeenCalledWith("him-1", "notes.md");
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
});
