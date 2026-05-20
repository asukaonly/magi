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
  // Re-export the WMO helper as a tiny stub — the sheet only uses it
  // to look up an emoji for a known code, so a deterministic
  // 65→🌧️ / 0→☀️ map keeps the chip-rendering test focused.
  weatherEmoji: (code: number | null | undefined) => {
    if (code == null) return null;
    const table: Record<number, string> = { 0: "☀️", 2: "⛅", 65: "🌧️" };
    return table[code] ?? null;
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

// Tiptap requires Selection / Range / contenteditable behaviors that
// jsdom doesn't fully implement. Stub the editor with a textarea-backed
// shim that respects the same prop contract — the sheet's flow (text
// input, save shortcut, paste callbacks) stays observable without
// trying to run ProseMirror in jsdom. The real editor still ships in
// production; we cover it via a manual smoke instead.
vi.mock("@/components/timeline/manual-entries/RichTextEditor", () => ({
  RichTextEditor: ({
    value,
    fallbackPlainText,
    onChange,
    onChangeText,
    onSubmitShortcut,
    placeholder,
    autoFocus,
  }: any) => {
    const initial =
      fallbackPlainText ??
      // Extract text from a single-paragraph doc if that's all there is.
      (value?.content?.[0]?.content?.[0]?.text ?? "");
    return (
      <textarea
        autoFocus={autoFocus}
        defaultValue={initial}
        placeholder={placeholder}
        onChange={(e) => {
          const text = e.target.value;
          onChangeText?.(text);
          onChange?.({
            type: "doc",
            content: [
              {
                type: "paragraph",
                content: text ? [{ type: "text", text }] : [],
              },
            ],
          });
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            onSubmitShortcut?.();
          }
        }}
      />
    );
  },
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
    weather: null, body_doc: null,
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

  it("calls manualEntriesApi.create with the entered body on save (quick mode = default)", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(<QuickEntrySheet open onClose={() => {}} onSaved={onSaved} />);
    await user.type(screen.getByPlaceholderText(/写下/), "一念之间");
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(createMock).toHaveBeenCalled());
    const payload = createMock.mock.calls[0][0];
    expect(payload.body).toBe("一念之间");
    expect(payload.attachment_refs).toEqual([]);
    // Quick mode is the default; the plain textarea doesn't produce a
    // body_doc. Promoting to long mode (the "转长文" button) is what
    // attaches one — see the separate test below.
    expect(payload.body_doc).toBeUndefined();
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("promotes to long mode and attaches body_doc when 转长文 is clicked", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(<QuickEntrySheet open onClose={() => {}} onSaved={onSaved} />);

    // Type in quick mode first, then upgrade.
    await user.type(screen.getByPlaceholderText(/写下/), "一念之间");
    await user.click(screen.getByRole("button", { name: "转长文" }));

    // After promotion, the mock RichTextEditor (textarea-shim) is mounted;
    // its onChange wraps the body into a ProseMirror doc on the next keystroke.
    // Add a trailing space so the editor emits an update for the existing text.
    await user.type(screen.getByPlaceholderText(/写下/), " ");

    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(createMock).toHaveBeenCalled());
    const payload = createMock.mock.calls[0][0];
    expect(payload.body).toContain("一念之间");
    expect(payload.body_doc).toMatchObject({
      type: "doc",
      content: [{ type: "paragraph" }],
    });
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

  it("renders weather chip when existing entry has weather", () => {
    render(
      <QuickEntrySheet
        open
        onClose={() => {}}
        existingEntry={{
          entry_id: "me-with-weather",
          body: "下雨天",
          mood: null,
          attachments: [],
          event_at: 100,
          created_at: 50,
          kind: "quick",
          location_label: "杭州",
          location_lat: null,
          location_lng: null,
          exclude_from_llm: false,
          user_pinned: false,
          deleted_at: null,
          l1_event_id: null,
          weather: { code: 65, temp_c: 15.4, fetched_at: 1 },
          body_doc: null,
        }}
      />
    );
    // Title attribute uniquely identifies the chip — assert the chip is in DOM.
    const chip = screen.getByTitle("自动获取的天气");
    expect(chip).toBeTruthy();
    // The temperature is rounded for display
    expect(chip.textContent).toContain("15°");
  });

  it("does not render weather chip when entry has no weather", () => {
    render(
      <QuickEntrySheet
        open
        onClose={() => {}}
        existingEntry={{
          entry_id: "me-no-weather",
          body: "啥也没有",
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
          weather: null,
          body_doc: null,
        }}
      />
    );
    expect(screen.queryByTitle("自动获取的天气")).toBeNull();
  });

  it("calls update instead of create when an existing entry is passed", async () => {
    updateMock.mockResolvedValue({
      entry_id: "me-existing", body: "updated", attachments: [],
      event_at: 100, created_at: 50, kind: "quick", mood: null,
      location_label: null, location_lat: null, location_lng: null,
      exclude_from_llm: false, user_pinned: false, deleted_at: null,
      l1_event_id: null, weather: null, body_doc: null,
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
          weather: null,
          body_doc: null,
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
