import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useInstallableSensors } from "@/hooks/useInstallableSensors";
import * as api from "@/api/modules/systemSuggestions";

describe("useInstallableSensors", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "listInstallable").mockResolvedValue([
      {
        plugin_id: "chrome-history",
        category: "browser_history",
        installed: false,
        rationale: { zh: "", en: "" },
        setup_time_estimate_seconds: 10,
        data_locality: "local_only",
      },
      {
        plugin_id: "git-activity",
        category: "code_activity",
        installed: true,
        rationale: { zh: "", en: "" },
        setup_time_estimate_seconds: 15,
        data_locality: "local_only",
      },
    ]);
  });

  it("populates items from listInstallable", async () => {
    const { result } = renderHook(() => useInstallableSensors());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.loading).toBe(false);
    expect(result.current.items[0].plugin_id).toBe("chrome-history");
  });

  it("falls back to an empty list when the request fails", async () => {
    vi.spyOn(api, "listInstallable").mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useInstallableSensors());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toEqual([]);
    expect(result.current.error).toBeInstanceOf(Error);
  });
});
