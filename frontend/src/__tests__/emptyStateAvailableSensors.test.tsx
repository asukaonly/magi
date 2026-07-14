import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { InstallableItem } from "@/api/modules/systemSuggestions";
import { EmptyStateAvailableSensors } from "@/components/empty-state/EmptyStateAvailableSensors";
import { useChatShellStore } from "@/stores/chat-shell";
import { usePluginInstallPanelStore } from "@/stores/pluginInstallPanel";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "zh-CN", resolvedLanguage: "zh-CN" },
  }),
}));

const mockUseInstallableSensors = vi.fn();
vi.mock("@/hooks/useInstallableSensors", () => ({
  useInstallableSensors: () => mockUseInstallableSensors(),
}));

function item(overrides: Partial<InstallableItem> = {}): InstallableItem {
  return {
    plugin_id: "chrome-history",
    name: "Chrome History",
    name_i18n: { "zh-CN": "Chrome 浏览器历史" },
    description: "Reads Chrome history",
    description_i18n: {},
    icon: "brand:googlechrome",
    category: "browser_history",
    installed: false,
    rationale: { zh: "浏览器建议", en: "Browser suggestion" },
    setup_time_estimate_seconds: 10,
    data_locality: "local_only",
    surfaces: {
      empty_state: {
        order: 10,
        rationale: { zh: "最近浏览内容", en: "Recent browsing" },
      },
      first_context: {
        order: 10,
        rationale: { zh: "从最近浏览开始", en: "Start from recent browsing" },
        scope: { zh: "最近 7 天", en: "Last 7 days" },
      },
    },
    ...overrides,
  };
}

describe("EmptyStateAvailableSensors", () => {
  beforeEach(() => {
    mockUseInstallableSensors.mockReturnValue({
      items: [],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    usePluginInstallPanelStore.getState().closePanel();
    useChatShellStore.setState({ activePanel: "none", settingsNavigationIntent: null });
  });

  it("does not flash cards while recommendations are loading", () => {
    mockUseInstallableSensors.mockReturnValue({ items: [], loading: true, refresh: vi.fn() });
    const { container } = render(<EmptyStateAvailableSensors />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders plugin-owned name, copy, icon, and ordering", () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [
        item({
          plugin_id: "calendar",
          name: "Calendar",
          name_i18n: { "zh-CN": "日历" },
          icon: "brand:googlecalendar",
          category: "calendar",
          surfaces: {
            empty_state: {
              order: 20,
              rationale: { zh: "查看近期日程", en: "See recent schedule" },
            },
          },
        }),
        item(),
      ],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });

    render(<EmptyStateAvailableSensors showBrowseAll={false} />);

    expect(screen.getByText("Chrome 浏览器历史")).toBeInTheDocument();
    expect(screen.getByText("最近浏览内容")).toBeInTheDocument();
    expect(screen.getByTestId("plugin-icon-googlechrome")).toBeInTheDocument();
    const buttons = screen.getAllByTestId(/empty-state-connect-/);
    expect(buttons.map((button) => button.dataset.testid)).toEqual([
      "empty-state-connect-chrome-history",
      "empty-state-connect-calendar",
    ]);
  });

  it("does not show a plugin that did not opt into the surface", () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [item({ surfaces: {} })],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors showBrowseAll={false} />);
    expect(screen.queryByTestId(/empty-state-connect-/)).not.toBeInTheDocument();
  });

  it("shows one representative per category and prefers an installed sibling", () => {
    mockUseInstallableSensors.mockReturnValue({
      items: [
        item(),
        item({
          plugin_id: "safari-history",
          name: "Safari History",
          name_i18n: { "zh-CN": "Safari 浏览器历史" },
          icon: "brand:safari",
          installed: true,
          surfaces: { empty_state: { order: 11 } },
        }),
      ],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSensors showBrowseAll={false} />);
    expect(screen.getByTestId("empty-state-connect-safari-history")).toBeInTheDocument();
    expect(screen.queryByTestId("empty-state-connect-chrome-history")).not.toBeInTheDocument();
  });

  it("shows at most three first-context categories with declared scope", () => {
    const candidates = [
      item(),
      item({
        plugin_id: "calendar",
        name: "Calendar",
        category: "calendar",
        surfaces: { first_context: { order: 20 } },
      }),
      item({
        plugin_id: "git-activity",
        name: "Git Activity",
        category: "code_activity",
        surfaces: { first_context: { order: 30 } },
      }),
      item({
        plugin_id: "photo-library",
        name: "Photo Library",
        category: "photos",
        surfaces: { first_context: { order: 40 } },
      }),
    ];
    render(
      <EmptyStateAvailableSensors
        variant="first_context"
        showBrowseAll={false}
        installableItems={candidates}
        installableLoading={false}
      />,
    );
    expect(screen.getByText("从最近浏览开始")).toBeInTheDocument();
    expect(screen.getByText("最近 7 天")).toBeInTheDocument();
    expect(screen.getAllByTestId(/empty-state-connect-/)).toHaveLength(3);
    expect(screen.queryByTestId("empty-state-connect-photo-library")).not.toBeInTheDocument();
  });

  it("opens the shared panel with plugin-owned display metadata", () => {
    render(
      <EmptyStateAvailableSensors
        showBrowseAll={false}
        installableItems={[item()]}
        installableLoading={false}
      />,
    );
    fireEvent.click(screen.getByTestId("empty-state-connect-chrome-history"));
    expect(usePluginInstallPanelStore.getState()).toMatchObject({
      open: true,
      pluginId: "chrome-history",
      pluginName: "Chrome 浏览器历史",
      pluginIcon: "brand:googlechrome",
      installMode: true,
    });
  });

  it("keeps the marketplace as the generic fallback", () => {
    render(<EmptyStateAvailableSensors />);
    fireEvent.click(screen.getByTestId("empty-state-browse-all"));
    expect(useChatShellStore.getState().activePanel).toBe("settings");
    expect(useChatShellStore.getState().settingsNavigationIntent).toEqual({
      section: "pluginsMarketplace",
    });
  });

  it("uses a focused source-page fallback when no recommendations exist", () => {
    render(<EmptyStateAvailableSensors variant="source_page" i18nKeyPrefix="timeline" />);

    const browseButton = screen.getByTestId("empty-state-browse-all");
    expect(browseButton).toHaveTextContent("timeline.emptyState.browseSources");
    expect(browseButton).toHaveClass("h-9", "rounded-lg");

    fireEvent.click(browseButton);
    expect(useChatShellStore.getState()).toMatchObject({
      activePanel: "settings",
      settingsNavigationIntent: { section: "pluginsMarketplace" },
    });
  });

  it("caps source-page recommendations at three categories", () => {
    const candidates = [
      item(),
      item({ plugin_id: "calendar", name: "Calendar", category: "calendar", surfaces: { empty_state: { order: 20 } } }),
      item({ plugin_id: "git-activity", name: "Git Activity", category: "code_activity", surfaces: { empty_state: { order: 30 } } }),
      item({ plugin_id: "photo-library", name: "Photo Library", category: "photos", surfaces: { empty_state: { order: 40 } } }),
    ];

    render(
      <EmptyStateAvailableSensors
        variant="source_page"
        i18nKeyPrefix="timeline"
        installableItems={candidates}
        installableLoading={false}
      />,
    );

    expect(screen.getByTestId("source-page-suggestions")).toBeInTheDocument();
    expect(screen.getAllByTestId(/empty-state-connect-/)).toHaveLength(3);
    expect(screen.queryByTestId("empty-state-connect-photo-library")).not.toBeInTheDocument();
  });
});
