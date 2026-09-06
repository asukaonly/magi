import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { InstallableItem } from "@/api/modules/systemSuggestions";
import { EmptyStateAvailableSources } from "@/components/empty-state/EmptyStateAvailableSources";
import { useChatShellStore } from "@/stores/chat-shell";
import { usePluginInstallPanelStore } from "@/stores/pluginInstallPanel";

const SVG_ICON = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4=";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "zh-CN", resolvedLanguage: "zh-CN" },
  }),
}));

const mockUseInstallableSources = vi.fn();
vi.mock("@/hooks/useInstallableSources", () => ({
  useInstallableSources: () => mockUseInstallableSources(),
}));

function item(overrides: Partial<InstallableItem> = {}): InstallableItem {
  return {
    plugin_id: "chrome-history",
    name: "Chrome History",
    name_i18n: { "zh-CN": "Chrome 浏览器历史" },
    description: "Reads Chrome history",
    description_i18n: {},
    icon: SVG_ICON,
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

describe("EmptyStateAvailableSources", () => {
  beforeEach(() => {
    mockUseInstallableSources.mockReturnValue({
      items: [],
      catalogMode: "full",
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    usePluginInstallPanelStore.getState().closePanel();
    useChatShellStore.setState({ activePanel: "none", settingsNavigationIntent: null });
  });

  it("does not flash cards while recommendations are loading", () => {
    mockUseInstallableSources.mockReturnValue({ items: [], loading: true, refresh: vi.fn() });
    const { container } = render(<EmptyStateAvailableSources />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders plugin-owned name, copy, icon, and ordering", () => {
    mockUseInstallableSources.mockReturnValue({
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

    render(<EmptyStateAvailableSources showBrowseAll={false} />);

    expect(screen.getByText("Chrome 浏览器历史")).toBeInTheDocument();
    expect(screen.getByText("最近浏览内容")).toBeInTheDocument();
    expect(screen.getByTestId("plugin-icon-asset")).toHaveAttribute("src", SVG_ICON);
    const buttons = screen.getAllByTestId(/empty-state-connect-/);
    expect(buttons.map((button) => button.dataset.testid)).toEqual([
      "empty-state-connect-chrome-history",
      "empty-state-connect-calendar",
    ]);
  });

  it("does not show a plugin that did not opt into the surface", () => {
    mockUseInstallableSources.mockReturnValue({
      items: [item({ surfaces: {} })],
      loading: false,
      error: null,
      refresh: vi.fn(),
    });
    render(<EmptyStateAvailableSources showBrowseAll={false} />);
    expect(screen.queryByTestId(/empty-state-connect-/)).not.toBeInTheDocument();
  });

  it("shows one representative per category and prefers an installed sibling", () => {
    mockUseInstallableSources.mockReturnValue({
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
    render(<EmptyStateAvailableSources showBrowseAll={false} />);
    expect(screen.getByTestId("empty-state-connect-safari-history")).toBeInTheDocument();
    expect(screen.queryByTestId("empty-state-connect-chrome-history")).not.toBeInTheDocument();
  });

  it("shows one featured and four alternative first-context categories", () => {
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
      item({
        plugin_id: "media-history",
        name: "Media History",
        category: "media_history",
        surfaces: { first_context: { order: 50 } },
      }),
      item({
        plugin_id: "terminal-history",
        name: "Terminal History",
        category: "terminal_history",
        surfaces: { first_context: { order: 60 } },
      }),
    ];
    render(
      <EmptyStateAvailableSources
        variant="first_context"
        showBrowseAll={false}
        installableItems={candidates}
        installableLoading={false}
      />,
    );
    expect(screen.getByText("从最近浏览开始")).toBeInTheDocument();
    expect(screen.getByText("最近 7 天")).toBeInTheDocument();
    expect(screen.getAllByTestId(/empty-state-connect-/)).toHaveLength(5);
    expect(screen.getByTestId("empty-state-connect-photo-library")).toBeInTheDocument();
    expect(screen.getByTestId("empty-state-connect-media-history")).toBeInTheDocument();
    expect(screen.queryByTestId("empty-state-connect-terminal-history")).not.toBeInTheDocument();
  });

  it("explains when the marketplace is unavailable and no local source exists", () => {
    const retry = vi.fn();

    render(
      <EmptyStateAvailableSources
        variant="first_context"
        showBrowseAll={false}
        installableItems={[]}
        installableCatalogMode="installed_only"
        installableLoading={false}
        onRetryInstallable={retry}
      />,
    );

    expect(screen.getByTestId("marketplace-unavailable")).toHaveTextContent(
      "emptyState.marketplaceUnavailableTitle",
    );
    expect(screen.queryByText("emptyState.noAvailable")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("empty-state-retry"));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("keeps local source cards visible when the marketplace is unavailable", () => {
    render(
      <EmptyStateAvailableSources
        variant="first_context"
        showBrowseAll={false}
        installableItems={[item({ installed: true })]}
        installableCatalogMode="installed_only"
        installableLoading={false}
      />,
    );

    expect(screen.getByTestId("marketplace-unavailable")).toHaveTextContent(
      "emptyState.marketplaceUnavailableWithLocal",
    );
    expect(
      screen.getByTestId("empty-state-connect-chrome-history"),
    ).toBeInTheDocument();
  });

  it("opens the shared panel with plugin-owned display metadata", () => {
    render(
      <EmptyStateAvailableSources
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
      pluginIcon: SVG_ICON,
      installMode: true,
    });
  });

  it("keeps the marketplace as the generic fallback", () => {
    render(<EmptyStateAvailableSources />);
    fireEvent.click(screen.getByTestId("empty-state-browse-all"));
    expect(useChatShellStore.getState().activePanel).toBe("settings");
    expect(useChatShellStore.getState().settingsNavigationIntent).toEqual({
      section: "pluginsMarketplace",
    });
  });

  it("uses a focused source-page fallback when no recommendations exist", () => {
    render(<EmptyStateAvailableSources variant="source_page" i18nKeyPrefix="timeline" />);

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
      <EmptyStateAvailableSources
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
