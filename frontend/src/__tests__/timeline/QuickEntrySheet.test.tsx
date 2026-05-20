import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

// `vi.mock` is hoisted to the top of the file, so any references it makes
// must also be created via `vi.hoisted` (otherwise the variables are
// undefined at mock-evaluation time).
const { createMock, updateMock, uploadMock } = vi.hoisted(() => ({
  createMock: vi.fn(),
  updateMock: vi.fn(),
  uploadMock: vi.fn(),
}));
vi.mock("@/api/modules/manualEntries", () => ({
  manualEntriesApi: {
    create: createMock,
    update: updateMock,
    uploadAsset: uploadMock,
    list: vi.fn(),
    remove: vi.fn(),
  },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key,
  }),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

// Lightweight Sheet stub — render content inline when open, hide when closed.
vi.mock("@/components/ui/sheet", () => ({
  Sheet: ({ children, open }: any) => (open ? <div role="dialog">{children}</div> : null),
  SheetContent: ({ children }: any) => <div>{children}</div>,
  SheetHeader: ({ children }: any) => <div>{children}</div>,
  SheetTitle: ({ children }: any) => <h2>{children}</h2>,
}));

import { QuickEntrySheet } from "@/components/timeline/manual-entries/QuickEntrySheet";

beforeEach(() => {
  createMock.mockReset();
  updateMock.mockReset();
  uploadMock.mockReset();
  createMock.mockResolvedValue({
    entry_id: "me-stub", body: "", attachments: [], event_at: 0,
    created_at: 0, kind: "quick", mood: null, location_label: null,
    location_lat: null, location_lng: null, exclude_from_llm: false,
    user_pinned: false, deleted_at: null, l1_event_id: null,
  });
});

describe("QuickEntrySheet", () => {
  it("disables save when body is empty and no attachments", () => {
    render(<QuickEntrySheet open onClose={() => {}} />);
    const saveBtn = screen.getByRole("button", { name: "保存" });
    expect(saveBtn).toBeDisabled();
  });

  it("enables save once body has content", async () => {
    const user = userEvent.setup();
    render(<QuickEntrySheet open onClose={() => {}} />);
    const textarea = screen.getByPlaceholderText(/写下/);
    await user.type(textarea, "今天还行");
    expect(screen.getByRole("button", { name: "保存" })).not.toBeDisabled();
  });

  it("calls manualEntriesApi.create with the entered body on save", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(<QuickEntrySheet open onClose={() => {}} onSaved={onSaved} />);
    await user.type(screen.getByPlaceholderText(/写下/), "一念之间");
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(createMock).toHaveBeenCalled());
    const payload = createMock.mock.calls[0][0];
    expect(payload.body).toBe("一念之间");
    expect(payload.attachment_refs).toEqual([]);
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("selecting and re-clicking a mood pill toggles the value", async () => {
    const user = userEvent.setup();
    render(<QuickEntrySheet open onClose={() => {}} />);
    const warmPill = screen.getByRole("button", { name: "warm" });
    expect(warmPill).toHaveAttribute("aria-pressed", "false");
    await user.click(warmPill);
    expect(warmPill).toHaveAttribute("aria-pressed", "true");
    await user.click(warmPill);
    expect(warmPill).toHaveAttribute("aria-pressed", "false");
  });

  it("Cmd+Enter inside the textarea triggers save", async () => {
    const user = userEvent.setup();
    render(<QuickEntrySheet open onClose={() => {}} />);
    const textarea = screen.getByPlaceholderText(/写下/);
    await user.type(textarea, "test");
    fireEvent.keyDown(textarea, { key: "Enter", metaKey: true });
    await waitFor(() => expect(createMock).toHaveBeenCalled());
  });

  it("calls update instead of create when an existing entry is passed", async () => {
    updateMock.mockResolvedValue({
      entry_id: "me-existing", body: "updated", attachments: [],
      event_at: 100, created_at: 50, kind: "quick", mood: null,
      location_label: null, location_lat: null, location_lng: null,
      exclude_from_llm: false, user_pinned: false, deleted_at: null,
      l1_event_id: null,
    });
    const user = userEvent.setup();
    render(
      <QuickEntrySheet
        open
        onClose={() => {}}
        existingEntry={{
          entry_id: "me-existing",
          body: "原文",
          mood: null,
          attachments: [],
          event_at: 100,
          created_at: 50,
          kind: "quick",
          location_label: null,
          location_lat: null,
          location_lng: null,
          exclude_from_llm: false,
          user_pinned: false,
          deleted_at: null,
          l1_event_id: null,
        }}
      />
    );
    const textarea = screen.getByPlaceholderText(/写下/);
    await user.clear(textarea);
    await user.type(textarea, "改动后");
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(updateMock).toHaveBeenCalledWith(
      "me-existing",
      expect.objectContaining({ body: "改动后" }),
    ));
    expect(createMock).not.toHaveBeenCalled();
  });
});
