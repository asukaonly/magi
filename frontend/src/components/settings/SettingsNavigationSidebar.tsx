import { type Dispatch, type SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight } from 'lucide-react';

import type { PluginContribution } from '@/api/modules/plugins';
import type { SourceStatusItem } from '@/api/modules/sources';
import { isNavGroup } from '@/constants/settings';
import { cn } from '@/lib/utils';
import type { NavItem } from '@/types/settings';
import { buildTimelineCapabilities } from '@/utils/timeline-capabilities';

interface SettingsNavigationSidebarProps {
  visibleNavItems: NavItem[];
  effectiveActiveSection: string;
  getGroupExpanded: (groupId: string) => boolean;
  setGroupExpanded: (groupId: string, expanded: boolean) => void;
  handleNavItemClick: (itemId: string, isGroup: boolean, firstChildId?: string) => void;
  sortedTimelineStatuses: SourceStatusItem[];
  timelineSelection: string | null;
  setTimelineSelection: Dispatch<SetStateAction<string | null>>;
  channelContributions: Array<{ contribution: PluginContribution }>;
  channelsSelection: string | null;
  setChannelsSelection: Dispatch<SetStateAction<string | null>>;
}

export function SettingsNavigationSidebar({
  visibleNavItems,
  effectiveActiveSection,
  getGroupExpanded,
  setGroupExpanded,
  handleNavItemClick,
  sortedTimelineStatuses,
  timelineSelection,
  setTimelineSelection,
  channelContributions,
  channelsSelection,
  setChannelsSelection,
}: SettingsNavigationSidebarProps) {
  const { t } = useTranslation('app');
  const timelineCapabilities = buildTimelineCapabilities(t, sortedTimelineStatuses);

  const isNavGroupActive = (item: NavItem) => {
    if (!isNavGroup(item)) {
      return effectiveActiveSection === item.id;
    }
    return item.children!.some((child) => child.id === effectiveActiveSection);
  };

  return (
    <nav className="flex w-56 shrink-0 flex-col bg-[hsl(var(--settings-shell)/0.68)] shadow-[inset_-1px_0_0_hsl(var(--settings-subnav-border)/0.22)]">
      <div className="flex h-16 shrink-0 items-center bg-[hsl(var(--settings-shell-elevated)/0.58)] px-6 backdrop-blur-sm">
        <p className="text-base font-bold leading-6 text-foreground">
          {t('settings.shellTitle')}
        </p>
      </div>
      <div className="flex-1 space-y-1.5 overflow-y-auto px-4 py-5">
        {visibleNavItems.map((item) => {
          const Icon = item.icon;
          const isActive = isNavGroupActive(item);
          const isExpandable = isNavGroup(item) || item.id === 'timeline' || item.id === 'channels';
          const isExpanded = isExpandable ? getGroupExpanded(item.id) : false;
          const ParentChevron = isExpandable && isExpanded ? ChevronDown : ChevronRight;
          return (
            <div key={item.id} className="space-y-1">
              <button
                type="button"
                onClick={() => {
                  if (isExpandable) {
                    handleNavItemClick(item.id, true, isNavGroup(item) ? item.children[0]?.id : item.id);
                  } else {
                    handleNavItemClick(item.id, false);
                  }
                }}
                aria-current={isActive ? 'page' : undefined}
                aria-expanded={isExpandable ? isExpanded : undefined}
                aria-label={t(`settings.tabs.${item.id}`)}
                className={cn(
                  'group flex w-full items-center justify-between rounded-lg px-3.5 py-2.5 text-left text-sm leading-6',
                  'transition-[background-color,color,box-shadow,transform] duration-200 ease-out',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35 focus-visible:ring-offset-0',
                  isActive
                    ? 'bg-[hsl(var(--settings-nav-active)/0.54)] text-foreground shadow-[0_10px_24px_hsl(var(--foreground)/0.055)]'
                    : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-nav-hover)/0.64)] hover:text-foreground'
                )}
              >
                <div className="flex min-w-0 items-center gap-3">
                  <Icon className={cn(
                    'h-4 w-4 shrink-0 transition-colors',
                    isActive
                      ? 'text-foreground'
                      : 'text-[hsl(var(--settings-nav-foreground))] group-hover:text-foreground'
                  )} />
                  <span className={cn('min-w-0 flex-1 truncate transition-colors', isActive ? 'font-semibold' : 'font-medium')}>
                    {t(`settings.tabs.${item.id}`)}
                  </span>
                </div>
                <ParentChevron className={cn(
                  'h-4 w-4 text-[hsl(var(--settings-nav-foreground))] transition-all duration-150',
                  isExpandable
                    ? isExpanded
                      ? 'opacity-100 translate-x-0'
                      : 'opacity-60 -translate-x-0'
                    : isActive
                      ? 'opacity-100 translate-x-0'
                      : 'opacity-0 -translate-x-1 group-hover:opacity-50 group-hover:translate-x-0'
                )} />
              </button>

              {isNavGroup(item) && isExpanded ? (
                <div className="ml-8 space-y-1 py-1">
                  {item.children.map((child) => {
                    const isChildActive = effectiveActiveSection === child.id;
                    return (
                      <button
                        key={child.id}
                        type="button"
                        onClick={() => {
                          setGroupExpanded(item.id, true);
                          handleNavItemClick(child.id, false);
                        }}
                        aria-current={isChildActive ? 'page' : undefined}
                        className={cn(
                          'flex w-full items-center justify-start rounded-md px-3 py-1.5 text-left text-[13px] leading-5 transition-colors duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35',
                          isChildActive
                            ? 'bg-[hsl(var(--settings-shell-elevated)/0.72)] text-foreground font-semibold'
                            : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.48)] hover:text-foreground'
                        )}
                      >
                        <span className="min-w-0 flex-1 truncate text-left">
                          {t(`settings.tabs.${child.id}`)}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : null}

              {item.id === 'timeline' && isActive && isExpanded ? (
                <div className="ml-8 space-y-1 py-1">
                  <button
                    type="button"
                    onClick={() => setTimelineSelection(null)}
                    data-testid="timeline-nav-overview"
                    aria-current={timelineSelection === null ? 'page' : undefined}
                    className={cn(
                      'flex w-full items-center rounded-md px-3 py-1.5 text-[13px] leading-5',
                      'transition-colors duration-200 ease-out',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35',
                      timelineSelection === null
                        ? 'bg-[hsl(var(--settings-shell-elevated)/0.72)] text-foreground font-semibold'
                        : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.48)] hover:text-foreground'
                    )}
                  >
                    {t('settings.timeline.nav.overview')}
                  </button>

                  {timelineCapabilities.map((capability) => {
                    const isSelected = timelineSelection === capability.id;
                    return (
                      <button
                        key={capability.id}
                        type="button"
                        onClick={() => setTimelineSelection(capability.id)}
                        data-testid={`timeline-nav-source-${capability.id}`}
                        aria-current={isSelected ? 'page' : undefined}
                        className={cn(
                          'flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-[13px] leading-5',
                          'transition-colors duration-200 ease-out',
                          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35',
                          isSelected
                            ? 'bg-[hsl(var(--settings-shell-elevated)/0.72)] text-foreground font-semibold'
                            : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.48)] hover:text-foreground'
                        )}
                      >
                        <span className="truncate">{capability.displayName}</span>
                        {capability.attentionCount > 0 ? (
                          <span className="ml-auto h-1.5 w-1.5 rounded-full bg-destructive" aria-hidden="true" />
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              ) : null}

              {item.id === 'channels' && isActive && isExpanded ? (
                <div className="ml-8 space-y-1 py-1">
                  <button
                    type="button"
                    onClick={() => setChannelsSelection(null)}
                    aria-current={channelsSelection === null ? 'page' : undefined}
                    className={cn(
                      'flex w-full items-center rounded-md px-3 py-1.5 text-[13px] leading-5',
                      'transition-colors duration-200 ease-out',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35',
                      channelsSelection === null
                        ? 'bg-[hsl(var(--settings-shell-elevated)/0.72)] text-foreground font-semibold'
                        : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.48)] hover:text-foreground'
                    )}
                  >
                    {t('settings.timeline.nav.overview')}
                  </button>
                  {channelContributions.map(({ contribution }) => {
                    const isSelected = channelsSelection === contribution.contribution_id;
                    return (
                      <button
                        key={contribution.contribution_id}
                        type="button"
                        onClick={() => setChannelsSelection(contribution.contribution_id)}
                        aria-current={isSelected ? 'page' : undefined}
                        className={cn(
                          'flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-[13px] leading-5',
                          'transition-colors duration-200 ease-out',
                          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/35',
                          isSelected
                            ? 'bg-[hsl(var(--settings-shell-elevated)/0.72)] text-foreground font-semibold'
                            : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.48)] hover:text-foreground'
                        )}
                      >
                        <span className="truncate">{contribution.display_name}</span>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </nav>
  );
}
