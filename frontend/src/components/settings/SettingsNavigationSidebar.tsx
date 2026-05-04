import { type Dispatch, type SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight } from 'lucide-react';

import type { PluginContribution } from '@/api/modules/plugins';
import type { SensorSourceStatusItem } from '@/api/modules/sensors';
import { isNavGroup } from '@/constants/settings';
import { cn } from '@/lib/utils';
import type { NavItem } from '@/types/settings';
import { getTimelineSourceDisplayName } from '@/utils/timeline-source-copy';

interface SettingsNavigationSidebarProps {
  visibleNavItems: NavItem[];
  effectiveActiveSection: string;
  getGroupExpanded: (groupId: string) => boolean;
  setGroupExpanded: (groupId: string, expanded: boolean) => void;
  handleNavItemClick: (itemId: string, isGroup: boolean, firstChildId?: string) => void;
  sortedTimelineStatuses: SensorSourceStatusItem[];
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

  const isNavGroupActive = (item: NavItem) => {
    if (!isNavGroup(item)) {
      return effectiveActiveSection === item.id;
    }
    return item.children!.some((child) => child.id === effectiveActiveSection);
  };

  return (
    <nav className="flex w-56 shrink-0 flex-col border-r border-[hsl(var(--settings-subnav-border)/0.72)] bg-[hsl(var(--settings-shell)/0.78)]">
      <div className="flex h-16 shrink-0 items-center border-b border-[hsl(var(--settings-subnav-border)/0.68)] bg-[hsl(var(--settings-shell-elevated)/0.94)] px-5 backdrop-blur-sm">
        <p className="text-base font-semibold leading-6 tracking-[0.01em] text-foreground">
          {t('settings.shellTitle')}
        </p>
      </div>
      <div className="flex-1 space-y-1 overflow-y-auto px-4 py-4">
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
                  'group flex w-full items-center justify-between rounded-md px-3 py-2.5 text-sm',
                  'transition-colors duration-150 ease-out',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
                  isActive
                    ? 'bg-[hsl(var(--settings-nav-active)/0.42)] text-foreground'
                    : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-nav-hover))] hover:text-foreground'
                )}
              >
                <div className="flex items-center gap-3">
                  <Icon className={cn(
                    'h-4 w-4 transition-colors',
                    isActive
                      ? 'text-foreground'
                      : 'text-[hsl(var(--settings-nav-foreground))] group-hover:text-foreground'
                  )} />
                  <span className={cn('transition-colors', isActive ? 'font-medium' : 'font-normal')}>
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
                <div className="ml-3 space-y-0.5 border-l border-[hsl(var(--settings-subnav-border)/0.78)] pl-4">
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
                          'flex w-full items-center rounded-sm px-2.5 py-1.5 text-[13px] transition-colors duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                          isChildActive
                            ? 'bg-[hsl(var(--settings-shell-elevated)/0.62)] text-foreground font-medium'
                            : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.52)] hover:text-foreground'
                        )}
                      >
                        {t(`settings.tabs.${child.id}`)}
                      </button>
                    );
                  })}
                </div>
              ) : null}

              {item.id === 'timeline' && isActive && isExpanded ? (
                <div className="ml-3 space-y-0.5 border-l border-[hsl(var(--settings-subnav-border)/0.78)] pl-4">
                  <button
                    type="button"
                    onClick={() => setTimelineSelection(null)}
                    data-testid="timeline-nav-overview"
                    aria-current={timelineSelection === null ? 'page' : undefined}
                    className={cn(
                      'flex w-full items-center rounded-sm px-2.5 py-1.5 text-[13px]',
                      'transition-colors duration-150 ease-out',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      timelineSelection === null
                        ? 'bg-[hsl(var(--settings-shell-elevated)/0.62)] text-foreground font-medium'
                        : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.52)] hover:text-foreground'
                    )}
                  >
                    {t('settings.timeline.nav.overview')}
                  </button>

                  {sortedTimelineStatuses.map((source) => {
                    const isSelected = timelineSelection === source.source_name;
                    const displayName = getTimelineSourceDisplayName(t, source);
                    return (
                      <button
                        key={source.source_name}
                        type="button"
                        onClick={() => setTimelineSelection(source.source_name)}
                        data-testid={`timeline-nav-source-${source.source_name}`}
                        aria-current={isSelected ? 'page' : undefined}
                        className={cn(
                          'flex w-full items-center gap-2 rounded-sm px-2.5 py-1.5 text-[13px]',
                          'transition-colors duration-150 ease-out',
                          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                          isSelected
                            ? 'bg-[hsl(var(--settings-shell-elevated)/0.62)] text-foreground font-medium'
                            : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.52)] hover:text-foreground'
                        )}
                      >
                        <span className="truncate">{displayName}</span>
                        {source.last_error ? (
                          <span className="ml-auto h-1.5 w-1.5 rounded-full bg-destructive" aria-hidden="true" />
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              ) : null}

              {item.id === 'channels' && isActive && isExpanded ? (
                <div className="ml-3 space-y-0.5 border-l border-[hsl(var(--settings-subnav-border)/0.78)] pl-4">
                  <button
                    type="button"
                    onClick={() => setChannelsSelection(null)}
                    aria-current={channelsSelection === null ? 'page' : undefined}
                    className={cn(
                      'flex w-full items-center rounded-sm px-2.5 py-1.5 text-[13px]',
                      'transition-colors duration-150 ease-out',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      channelsSelection === null
                        ? 'bg-[hsl(var(--settings-shell-elevated)/0.62)] text-foreground font-medium'
                        : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.52)] hover:text-foreground'
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
                          'flex w-full items-center gap-2 rounded-sm px-2.5 py-1.5 text-[13px]',
                          'transition-colors duration-150 ease-out',
                          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                          isSelected
                            ? 'bg-[hsl(var(--settings-shell-elevated)/0.62)] text-foreground font-medium'
                            : 'text-[hsl(var(--settings-nav-foreground))] hover:bg-[hsl(var(--settings-shell-elevated)/0.52)] hover:text-foreground'
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