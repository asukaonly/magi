import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  confirmMock,
  deleteMock,
  getMock,
  pickDirectoryMock,
  pickMarkdownFilesMock,
  previewMock,
  resumeMock,
} = vi.hoisted(() => ({
  confirmMock: vi.fn(),
  deleteMock: vi.fn(),
  getMock: vi.fn(),
  pickDirectoryMock: vi.fn(),
  pickMarkdownFilesMock: vi.fn(),
  previewMock: vi.fn(),
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

vi.mock("@/runtime/desktop", () => ({
  pickDirectory: (...args: unknown[]) => pickDirectoryMock(...args),
  pickMarkdownFiles: (...args: unknown[]) => pickMarkdownFilesMock(...args),
}));

vi.mock("@/api/modules/historyImports", () => ({
  historyImportsApi: {
    previewMarkdown: (...args: unknown[]) => previewMock(...args),
    get: (...args: unknown[]) => getMock(...args),
    confirm: (...args: unknown[]) => confirmMock(...args),
    resume: (...args: unknown[]) => resumeMock(...args),
    delete: (...args: unknown[]) => deleteMock(...args),
  },
}));

import FirstContextHistoryImport from "@/components/onboarding/FirstContextHistoryImport";
import type { HistoryImportJob } from "@/api/modules/historyImports";

function chatPreview(): HistoryImportJob {
  return {
    job_id: "him-1",
    source_type: "markdown",
    source_files: ["chat.md"],
    detected_kind: "chat",
    status: "preview_ready",
    total_records: 4,
    meaningful_records: 4,
    quick_target_records: 200,
    quick_max_records: 500,
    quick_imported_count: 0,
    imported_count: 0,
    projected_count: 0,
    self_participants: [],
    warnings: [],
    quick_ready: false,
    error_code: null,
    participants: [
      {
        name: "Me",
        is_document_author: false,
        message_count: 2,
        meaningful_count: 2,
        sample: "I started learning pottery.",
      },
      {
        name: "Alice",
        is_document_author: false,
        message_count: 2,
        meaningful_count: 2,
        sample: "What do you like about it?",
      },
    ],
    preview_records: [
      {
        source_name: "chat.md",
        session_id: "session-1",
        session_seq: 0,
        speaker_name: "Me",
        is_document_author: false,
        content: "I started learning pottery.",
        event_at: 1_800_000_000,
        timestamp_confidence: "file_order",
      },
    ],
  };
}

function readyJob(): HistoryImportJob {
  return {
    ...chatPreview(),
    status: "ready",
    quick_imported_count: 4,
    imported_count: 4,
    self_participants: ["Me"],
    quick_ready: true,
  };
}

describe("FirstContextHistoryImport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pickMarkdownFilesMock.mockResolvedValue(["/tmp/chat.md"]);
    pickDirectoryMock.mockResolvedValue(undefined);
    previewMock.mockResolvedValue(chatPreview());
    confirmMock.mockResolvedValue(readyJob());
    getMock.mockResolvedValue(readyJob());
    deleteMock.mockResolvedValue(undefined);
  });

  it("previews Markdown, confirms the user's speaker, and reaches quick-ready", async () => {
    const user = userEvent.setup();
    const onJobUpdate = vi.fn();
    render(
      <FirstContextHistoryImport onJobUpdate={onJobUpdate} />,
    );

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.picker.files",
      }),
    );
    expect(await screen.findByTestId("history-import-preview")).toBeInTheDocument();
    expect(previewMock).toHaveBeenCalledWith(["/tmp/chat.md"]);
    expect(
      screen.getByText("firstContext.history.preview.sourceOrder"),
    ).toBeInTheDocument();

    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(2);
    expect(checkboxes[0]).toBeChecked();
    expect(checkboxes[1]).not.toBeChecked();

    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.preview.confirm",
      }),
    );
    expect(confirmMock).toHaveBeenCalledWith("him-1", {
      selfParticipants: ["Me"],
      confirmPersonalWriting: false,
    });
    expect(await screen.findByTestId("history-import-ready")).toBeInTheDocument();
    expect(onJobUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        job_id: "him-1",
        quick_ready: true,
        quick_imported_count: 4,
      }),
    );
  });

  it("requires explicit authorship confirmation for personal writing", async () => {
    const user = userEvent.setup();
    previewMock.mockResolvedValue({
      ...chatPreview(),
      detected_kind: "document",
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
          ...chatPreview().preview_records[0],
          is_document_author: true,
          speaker_name: "__document_author__",
        },
      ],
    } satisfies HistoryImportJob);

    render(<FirstContextHistoryImport onJobUpdate={vi.fn()} />);
    await user.click(
      screen.getByRole("button", {
        name: "firstContext.history.picker.files",
      }),
    );
    const confirm = await screen.findByRole("button", {
      name: "firstContext.history.preview.confirm",
    });
    expect(confirm).toBeDisabled();

    await user.click(screen.getByRole("checkbox"));
    await waitFor(() => expect(confirm).toBeEnabled());
  });

  it("deletes the preview before choosing different files", async () => {
    const user = userEvent.setup();
    const onJobUpdate = vi.fn();
    render(<FirstContextHistoryImport onJobUpdate={onJobUpdate} />);

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
});
