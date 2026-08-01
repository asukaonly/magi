import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";

// `vi.mock` is hoisted to the top of the file, so any references it makes
// must also be created via `vi.hoisted` (otherwise the variables are
// undefined at mock-evaluation time).
const {
  createMock,
  updateMock,
  clearWeatherMock,
  uploadMock,
  toastErrorMock,
  toastSuccessMock,
} = vi.hoisted(() => ({
  createMock: vi.fn(),
  updateMock: vi.fn(),
  clearWeatherMock: vi.fn(),
  uploadMock: vi.fn(),
  toastErrorMock: vi.fn(),
  toastSuccessMock: vi.fn(),
}));
vi.mock("@/api/modules/manualEntries", () => ({
  manualEntriesApi: {
    create: createMock,
    update: updateMock,
    clearWeather: clearWeatherMock,
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
  toast: { error: toastErrorMock, success: toastSuccessMock },
}));

// Lightweight Dialog stub — the production component swapped from Sheet
// to Dialog (Dialog already centers; Sheet's bottom variant fought us).
// Render content inline when open, hide when closed. Children are
// passed straight through so the structural tests still find them.
vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ children, open }: any) => (open ? <div role="dialog">{children}</div> : null),
  DialogContent: ({ children }: any) => <div>{children}</div>,
  DialogHeader: ({ children }: any) => <div>{children}</div>,
  DialogTitle: ({ children }: any) => <h2>{children}</h2>,
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
      <>
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
        <button
          type="button"
          aria-label="structured doc a"
          onClick={() => onChange?.({
            type: "doc",
            content: [{ type: "paragraph", attrs: { variant: "a" } }],
          })}
        />
        <button
          type="button"
          aria-label="structured doc b"
          onClick={() => onChange?.({
            type: "doc",
            content: [{ type: "paragraph", attrs: { variant: "b" } }],
          })}
        />
      </>
    );
  },
}));

import { QuickEntrySheet } from "@/components/timeline/manual-entries/QuickEntrySheet";
import { dispatchAppEvent } from "@/constants/events";

beforeEach(() => {
  createMock.mockReset();
  updateMock.mockReset();
  clearWeatherMock.mockReset();
  uploadMock.mockReset();
  toastErrorMock.mockReset();
  toastSuccessMock.mockReset();
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:quick-entry-test"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
  createMock.mockResolvedValue({
    entry_id: "me-stub", body: "", attachments: [], event_at: 0,
    created_at: 0, kind: "quick", mood: null, location_label: null,
    location_lat: null, location_lng: null, exclude_from_llm: false,
    user_pinned: false, deleted_at: null, l1_event_id: null,
    weather: null, body_doc: null, memory_status: "ready",
  });
});

describe("QuickEntrySheet", () => {
  it("aborts an unfinished upload and releases its preview on a full clear", async () => {
    uploadMock.mockImplementation((_file: File, options: { signal: AbortSignal }) => (
      new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => {
          reject(new DOMException('aborted', 'AbortError'));
        });
      })
    ));
    const { container } = render(<QuickEntrySheet open onClose={() => {}} />);
    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]');
    fireEvent.change(screen.getByPlaceholderText(/写下/), {
      target: { value: 'draft survives a failed clear' },
    });

    fireEvent.change(fileInput!, {
      target: { files: [new File(['image'], 'private.png', { type: 'image/png' })] },
    });
    await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(1));
    const signal = uploadMock.mock.calls[0][1].signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    act(() => dispatchAppEvent.memoryClearStarted());

    await waitFor(() => expect(signal.aborted).toBe(true));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:quick-entry-test');
    expect(screen.getByPlaceholderText(/写下/)).toHaveValue(
      'draft survives a failed clear',
    );
    act(() => dispatchAppEvent.memoryCleared());

    await waitFor(() => expect(screen.getByPlaceholderText(/写下/)).toHaveValue(''));
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

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
    expect(payload.entry_id).toMatch(/^me-[0-9a-f-]+$/);
    expect(payload.body).toBe("一念之间");
    expect(payload.attachment_refs).toEqual([]);
    // Quick mode is the default; the plain textarea doesn't produce a
    // body_doc. Promoting to long mode (the "转长文" button) is what
    // attaches one — see the separate test below.
    expect(payload.body_doc).toBeUndefined();
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("closes with a clear success message when memory completion is pending", async () => {
    createMock.mockResolvedValueOnce({
      entry_id: "me-pending", body: "先记下来", attachments: [], event_at: 10,
      created_at: 10, kind: "quick", mood: null, location_label: null,
      location_lat: null, location_lng: null, exclude_from_llm: false,
      user_pinned: false, deleted_at: null, l1_event_id: null,
      weather: null, body_doc: null, memory_status: "pending",
    });
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onSaved = vi.fn();
    render(<QuickEntrySheet open onClose={onClose} onSaved={onSaved} />);

    await user.type(screen.getByPlaceholderText(/写下/), "先记下来");
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(toastSuccessMock).toHaveBeenCalledWith("已记录，相关记忆稍后完成");
      expect(onSaved).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  it("reuses one draft identity and timestamp after an unknown create failure", async () => {
    createMock
      .mockRejectedValueOnce(new Error("connection closed"))
      .mockResolvedValueOnce({
        entry_id: "me-retried", body: "重试", attachments: [], event_at: 10,
        created_at: 10, kind: "quick", mood: null, location_label: null,
        location_lat: null, location_lng: null, exclude_from_llm: false,
        user_pinned: false, deleted_at: null, l1_event_id: "event-1",
        weather: null, body_doc: null, memory_status: "ready",
      });
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<QuickEntrySheet open onClose={onClose} />);

    await user.type(screen.getByPlaceholderText(/写下/), "重试");
    const save = screen.getByRole("button", { name: "保存" });
    await user.click(save);
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(save).not.toBeDisabled());
    await user.click(save);
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(2));

    const first = createMock.mock.calls[0][0];
    const second = createMock.mock.calls[1][0];
    expect(second.entry_id).toBe(first.entry_id);
    expect(second.event_at).toBe(first.event_at);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("ignores a late automatic location after an unknown create result", async () => {
    createMock
      .mockRejectedValueOnce(new Error("connection closed"))
      .mockResolvedValueOnce({
        entry_id: "me-retried", body: "重试", attachments: [], event_at: 10,
        created_at: 10, kind: "quick", mood: null, location_label: null,
        location_lat: null, location_lng: null, exclude_from_llm: false,
        user_pinned: false, deleted_at: null, l1_event_id: "event-1",
        weather: null, body_doc: null, memory_status: "ready",
      });
    const user = userEvent.setup();
    const onClose = vi.fn();
    const { rerender } = render(
      <QuickEntrySheet
        open
        onClose={onClose}
        initialLocationLabel={null}
      />,
    );

    await user.type(screen.getByPlaceholderText(/写下/), "重试");
    const save = screen.getByRole("button", { name: "保存" });
    await user.click(save);
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(save).not.toBeDisabled());

    rerender(
      <QuickEntrySheet
        open
        onClose={onClose}
        initialLocationLabel="杭州"
      />,
    );
    expect(screen.queryByText("杭州")).toBeNull();

    await user.click(save);
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(2));
    expect(createMock.mock.calls[1][0]).toEqual(createMock.mock.calls[0][0]);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("rotates the create identity when the body changes after a failed save", async () => {
    createMock.mockRejectedValue(new Error("connection closed"));
    const user = userEvent.setup();
    render(<QuickEntrySheet open onClose={() => {}} />);

    const textarea = screen.getByPlaceholderText(/写下/);
    const save = screen.getByRole("button", { name: "保存" });
    await user.type(textarea, "第一版");
    await user.click(save);
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(save).not.toBeDisabled());

    await user.type(textarea, "，改过");
    await user.click(save);
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(2));

    expect(createMock.mock.calls[1][0].entry_id).not.toBe(
      createMock.mock.calls[0][0].entry_id,
    );
  });

  it("rotates the create identity for structured body, mood, location, time, and ready attachments", async () => {
    createMock.mockRejectedValue(new Error("connection closed"));
    uploadMock.mockResolvedValue({ asset_ref: "asset-ready" });
    const user = userEvent.setup();
    const { container } = render(<QuickEntrySheet open onClose={() => {}} />);

    await user.type(screen.getByPlaceholderText(/写下/), "同一段正文");
    await user.click(screen.getByRole("tab", { name: "长文" }));
    await user.click(screen.getByRole("button", { name: "structured doc a" }));

    const save = screen.getByRole("button", { name: "保存" });
    const saveAttempt = async (expectedCount: number) => {
      await user.click(save);
      await waitFor(() => expect(createMock).toHaveBeenCalledTimes(expectedCount));
      await waitFor(() => expect(save).not.toBeDisabled());
      return createMock.mock.calls[expectedCount - 1][0];
    };

    const structuredA = await saveAttempt(1);
    await user.click(screen.getByRole("button", { name: "structured doc b" }));
    const structuredB = await saveAttempt(2);
    expect(structuredB.entry_id).not.toBe(structuredA.entry_id);
    expect(structuredB.body).toBe(structuredA.body);

    await user.click(screen.getByRole("button", { name: /心情/ }));
    await user.click(screen.getByRole("button", { name: "舒适 / 放松" }));
    const withMood = await saveAttempt(3);
    expect(withMood.entry_id).not.toBe(structuredB.entry_id);

    await user.click(screen.getByRole("button", { name: "加地点" }));
    const locationInput = screen.getByPlaceholderText("输入地点");
    await user.type(locationInput, "杭州");
    fireEvent.blur(locationInput);
    const withLocation = await saveAttempt(4);
    expect(withLocation.entry_id).not.toBe(withMood.entry_id);

    await user.click(screen.getByRole("button", { name: /刚才/ }));
    await user.click(screen.getByRole("button", { name: "1 小时前" }));
    const withTime = await saveAttempt(5);
    expect(withTime.entry_id).not.toBe(withLocation.entry_id);

    const fileInput = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    fireEvent.change(fileInput!, {
      target: { files: [new File(["image"], "photo.png", { type: "image/png" })] },
    });
    await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(save).not.toBeDisabled());
    const withAttachment = await saveAttempt(6);
    expect(withAttachment.entry_id).not.toBe(withTime.entry_id);
    expect(withAttachment.attachment_refs).toEqual(["asset-ready"]);
  });

  it("rotates only a new-entry identity after a nested forgotten-range error", async () => {
    createMock
      .mockRejectedValueOnce({
        code: "UNKNOWN_ERROR",
        details: {
          code: "manual_entry_memory_forgotten",
          reason: "time_range",
          source_preserved: false,
          retry_as_new: true,
        },
      })
      .mockResolvedValueOnce({
        entry_id: "me-after-conflict", body: "重试", attachments: [], event_at: 10,
        created_at: 10, kind: "quick", mood: null, location_label: null,
        location_lat: null, location_lng: null, exclude_from_llm: false,
        user_pinned: false, deleted_at: null, l1_event_id: "event-1",
        weather: null, body_doc: null, memory_status: "ready",
      });
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<QuickEntrySheet open onClose={onClose} />);

    await user.type(screen.getByPlaceholderText(/写下/), "重试");
    const save = screen.getByRole("button", { name: "保存" });
    await user.click(save);
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    expect(toastErrorMock).toHaveBeenCalledWith(
      "这个时间段已被遗忘，请调整时间后重新保存",
    );
    expect(onClose).not.toHaveBeenCalled();

    await waitFor(() => expect(save).not.toBeDisabled());
    await user.click(save);
    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(2));
    expect(createMock.mock.calls[1][0].entry_id).not.toBe(
      createMock.mock.calls[0][0].entry_id,
    );
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("preserves the typed draft when an automatic location arrives later", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <QuickEntrySheet open onClose={() => {}} initialLocationLabel={null} />,
    );

    const textarea = screen.getByPlaceholderText(/写下/);
    await user.type(textarea, "不会被清空");
    rerender(
      <QuickEntrySheet open onClose={() => {}} initialLocationLabel="杭州" />,
    );

    expect(screen.getByPlaceholderText(/写下/)).toHaveValue("不会被清空");
    expect(screen.getByText("杭州")).toBeInTheDocument();

    rerender(
      <QuickEntrySheet open onClose={() => {}} initialLocationLabel={null} />,
    );
    expect(screen.getByText("杭州")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/写下/)).toHaveValue("不会被清空");

    rerender(
      <QuickEntrySheet open onClose={() => {}} initialLocationLabel="" />,
    );
    expect(screen.getByText("杭州")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "杭州" }));
    const locationInput = screen.getByPlaceholderText("输入地点");
    await user.clear(locationInput);
    await user.type(locationInput, "北京");
    fireEvent.blur(locationInput);
    rerender(
      <QuickEntrySheet open onClose={() => {}} initialLocationLabel="上海" />,
    );

    expect(screen.getByPlaceholderText(/写下/)).toHaveValue("不会被清空");
    expect(screen.getByText("北京")).toBeInTheDocument();
    expect(screen.queryByText("上海")).toBeNull();
  });

  it("promotes to long mode and attaches body_doc when the 长文 toggle is clicked", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(<QuickEntrySheet open onClose={() => {}} onSaved={onSaved} />);

    // Type in quick mode first, then upgrade via the segmented toggle.
    await user.type(screen.getByPlaceholderText(/写下/), "一念之间");
    await user.click(screen.getByRole("tab", { name: "长文" }));

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

  it("picking a mood from the popover applies it to the save payload", async () => {
    const user = userEvent.setup();
    render(<QuickEntrySheet open onClose={() => {}} />);
    // Mood is now a popover-driven chip — open it first, then the
    // 5-emoji palette becomes interactive. The trigger button shows
    // "心情" placeholder text when no mood is selected.
    await user.click(screen.getByRole("button", { name: /心情/ }));
    const warmPill = screen.getByRole("button", { name: "舒适 / 放松" });
    expect(warmPill).toHaveAttribute("aria-pressed", "false");
    await user.click(warmPill);
    // Verify the selection landed by saving and inspecting payload.mood.
    // (We don't try to re-open the popover and re-read aria-pressed —
    // that's fragile in jsdom with Radix Portal'd content.)
    await user.type(screen.getByPlaceholderText(/写下/), "x");
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(createMock).toHaveBeenCalled());
    expect(createMock.mock.calls[0][0].mood).toBe("warm");
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

  it("does not report success when weather clearing finds a forgotten source", async () => {
    updateMock.mockResolvedValueOnce({
      entry_id: "me-with-weather", body: "下雨天", attachments: [],
      event_at: 100, created_at: 50, kind: "quick", mood: null,
      location_label: "杭州", location_lat: null, location_lng: null,
      exclude_from_llm: false, user_pinned: false, deleted_at: null,
      l1_event_id: "event-weather", weather: { code: 65, temp_c: 15.4 },
      body_doc: null,
    });
    clearWeatherMock.mockRejectedValueOnce({
      code: "UNKNOWN_ERROR",
      details: {
        code: "manual_entry_memory_forgotten",
        reason: "source_reference",
        source_preserved: false,
        retry_as_new: true,
      },
    });
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <QuickEntrySheet
        open
        onClose={onClose}
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
          l1_event_id: "event-weather",
          weather: { code: 65, temp_c: 15.4, fetched_at: 1 },
          body_doc: null,
        }}
      />,
    );

    await user.click(screen.getByRole("button", { name: "清除天气" }));
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(clearWeatherMock).toHaveBeenCalledTimes(1));
    expect(toastErrorMock).toHaveBeenCalledWith(
      "这条记录已被遗忘，如需保留请另存",
    );
    expect(toastSuccessMock).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
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

  it("keeps a forgotten-range retry in update mode for an existing entry", async () => {
    updateMock
      .mockRejectedValueOnce({
        code: "UNKNOWN_ERROR",
        details: {
          code: "manual_entry_memory_forgotten",
          reason: "time_range",
          source_preserved: true,
          retry_as_new: false,
        },
      })
      .mockResolvedValueOnce({
        entry_id: "me-existing", body: "改动后", attachments: [],
        event_at: 100, created_at: 50, kind: "quick", mood: null,
        location_label: null, location_lat: null, location_lng: null,
        exclude_from_llm: false, user_pinned: false, deleted_at: null,
        l1_event_id: "event-existing", weather: null, body_doc: null,
      });
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <QuickEntrySheet
        open
        onClose={onClose}
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
          l1_event_id: "event-existing",
          weather: null,
          body_doc: null,
        }}
      />,
    );
    const textarea = screen.getByPlaceholderText(/写下/);
    await user.clear(textarea);
    await user.type(textarea, "改动后");
    const save = screen.getByRole("button", { name: "保存" });

    await user.click(save);
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(toastErrorMock).toHaveBeenCalledWith(
      "这个时间段已被遗忘，请调整时间后重新保存",
    );
    expect(onClose).not.toHaveBeenCalled();

    await waitFor(() => expect(save).not.toBeDisabled());
    const popoverTriggers = screen.getAllByRole("button").filter(
      (button) => button.getAttribute("aria-haspopup") === "dialog",
    );
    await user.click(popoverTriggers[1]);
    await user.click(screen.getByRole("button", { name: "1 小时前" }));
    await user.click(save);
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(2));

    expect(updateMock.mock.calls[0][0]).toBe("me-existing");
    expect(updateMock.mock.calls[1][0]).toBe("me-existing");
    expect(createMock).not.toHaveBeenCalled();
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });

  it("retries a terminalized edit as a new entry after the time changes", async () => {
    updateMock.mockRejectedValueOnce({
      code: "UNKNOWN_ERROR",
      details: {
        code: "manual_entry_memory_forgotten",
        reason: "source_reference",
        source_preserved: false,
        retry_as_new: true,
      },
    });
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <QuickEntrySheet
        open
        onClose={onClose}
        existingEntry={{
          entry_id: "me-terminalized",
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
          l1_event_id: "event-terminalized",
          weather: null,
          body_doc: null,
        }}
      />,
    );
    const textarea = screen.getByPlaceholderText(/写下/);
    await user.clear(textarea);
    await user.type(textarea, "改动后");
    const save = screen.getByRole("button", { name: "保存" });

    await user.click(save);
    await waitFor(() => expect(updateMock).toHaveBeenCalledTimes(1));
    expect(toastErrorMock).toHaveBeenCalledWith(
      "这条记录已被遗忘，如需保留请另存",
    );
    expect(createMock).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();

    await waitFor(() => expect(save).not.toBeDisabled());
    const popoverTriggers = screen.getAllByRole("button").filter(
      (button) => button.getAttribute("aria-haspopup") === "dialog",
    );
    await user.click(popoverTriggers[1]);
    await user.click(screen.getByRole("button", { name: "1 小时前" }));
    await user.click(save);

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    expect(createMock.mock.calls[0][0]).toMatchObject({
      entry_id: expect.stringMatching(/^me-[0-9a-f-]+$/),
      body: "改动后",
    });
    expect(updateMock).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  });
});
