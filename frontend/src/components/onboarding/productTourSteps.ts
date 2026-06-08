import type { InstallableItem } from '@/api/modules/systemSuggestions';

export interface ProductTourStep {
  /** data-testid of the element to spotlight. */
  targetTestId: string;
  /** i18n keys (app namespace) for title + body. */
  titleKey: string;
  bodyKey: string;
  /** When true, this step shows the "connect a data source" action. */
  connect?: boolean;
}

export const PRODUCT_TOUR_STEPS: ProductTourStep[] = [
  { targetTestId: 'tour-target-conversation', titleKey: 'productTour.chat.title', bodyKey: 'productTour.chat.body' },
  { targetTestId: 'tour-target-timeline', titleKey: 'productTour.timeline.title', bodyKey: 'productTour.timeline.body', connect: true },
  { targetTestId: 'tour-target-memory', titleKey: 'productTour.memory.title', bodyKey: 'productTour.memory.body' },
  { targetTestId: 'tour-target-bell', titleKey: 'productTour.bell.title', bodyKey: 'productTour.bell.body' },
];

// Zero-config (one-click, no dir-pick / login) source priority. These have empty
// local_requirements in their suggestion descriptors. Lead with browser history
// (universal data, no permission prompt). InstallableItem carries no zero-config
// flag, so we intersect this allowlist with the availability-filtered list.
const ZERO_CONFIG_PRIORITY = ['chrome-history', 'screen-time', 'system-media', 'screenshot_timeline'];

export function pickZeroConfigSource(items: InstallableItem[]): InstallableItem | null {
  for (const id of ZERO_CONFIG_PRIORITY) {
    const hit = items.find((i) => i.plugin_id === id);
    if (hit) return hit;
  }
  return null;
}
