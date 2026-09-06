import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { useInstallableSources } from "@/hooks/useInstallableSources";
import * as api from "@/api/modules/systemSuggestions";

describe("useInstallableSources", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "listInstallable").mockResolvedValue({
      catalog_mode: "full",
      items: [{
        plugin_id: "chrome-history",
        name: "Chrome History",
        name_i18n: {},
        description: "Chrome history",
        description_i18n: {},
        icon: "brand:googlechrome",
        category: "browser_history",
        installed: false,
        rationale: { zh: "", en: "" },
        setup_time_estimate_seconds: 10,
        data_locality: "local_only",
        surfaces: { empty_state: { order: 10 } },
      }, {
        plugin_id: "git-activity",
        name: "Git Activity",
        name_i18n: {},
        description: "Git activity",
        description_i18n: {},
        icon: "brand:git",
        category: "code_activity",
        installed: true,
        rationale: { zh: "", en: "" },
        setup_time_estimate_seconds: 15,
        data_locality: "local_only",
        surfaces: { empty_state: { order: 20 } },
      }],
    });
  });

  it("populates items from listInstallable", async () => {
    const { result } = renderHook(() => useInstallableSources());
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.loading).toBe(false);
    expect(result.current.catalogMode).toBe("full");
    expect(result.current.items[0].plugin_id).toBe("chrome-history");
  });

  it("falls back to an empty list when the request fails", async () => {
    vi.spyOn(api, "listInstallable").mockRejectedValue(new Error("boom"));
    const { result } = renderHook(() => useInstallableSources());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toEqual([]);
    expect(result.current.catalogMode).toBeNull();
    expect(result.current.error).toBeInstanceOf(Error);
  });
});
