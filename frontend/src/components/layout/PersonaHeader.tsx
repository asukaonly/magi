import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus } from 'lucide-react';
import { ChatRoleAvatar } from '@/components/chat/ChatRoleAvatar';
import { useActivePersona } from '@/hooks/useActivePersona';
import { personasApi } from '@/api/modules/personas';

const MS_PER_DAY = 1000 * 60 * 60 * 24;

const computeCompanionDays = (createdAtSeconds: number): number => {
  if (!Number.isFinite(createdAtSeconds) || createdAtSeconds <= 0) {
    return 0;
  }
  const diffMs = Date.now() - createdAtSeconds * 1000;
  if (diffMs <= 0) {
    return 0;
  }
  return Math.floor(diffMs / MS_PER_DAY);
};

export interface PersonaHeaderProps {
  onCreateChat?: () => void;
}

export const PersonaHeader = ({ onCreateChat }: PersonaHeaderProps) => {
  const { t, i18n } = useTranslation('app');
  const { persona } = useActivePersona();

  const companionLabel = useMemo(() => {
    if (!persona) return '';
    const days = computeCompanionDays(persona.createdAt);
    if (days === 0) return t('shell.personaCompanion.firstDay');
    if (days === 1) return t('shell.personaCompanion.yesterday');
    if (days >= 365) {
      const years = Math.floor(days / 365);
      const remainder = days % 365;
      return t('shell.personaCompanion.companionYears', { years, days: remainder });
    }
    return t('shell.personaCompanion.companionDays', { count: days });
  }, [persona, t]);

  const tooltipLabel = useMemo(() => {
    if (!persona) return '';
    const dateLabel = new Intl.DateTimeFormat(i18n.language || undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    }).format(new Date(persona.createdAt * 1000));
    return t('shell.personaCompanion.tooltip', { name: persona.name, date: dateLabel });
  }, [persona, t, i18n.language]);

  if (!persona) {
    return null;
  }

  return (
    <div
      className="flex items-center gap-3 px-4 py-4"
      data-testid="sidebar-persona-header"
      title={tooltipLabel}
    >
      <ChatRoleAvatar
        role="assistant"
        assistantName={persona.name}
        assistantAvatar={personasApi.getAvatarUrl(persona.avatarPath)}
        avatarState="idle"
      />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-[hsl(var(--sidebar-active-foreground))]">
          {persona.name}
        </div>
        <div className="truncate text-xs leading-5 text-[hsl(var(--sidebar-muted))]">
          {companionLabel}
        </div>
      </div>
      {onCreateChat ? (
        <button
          type="button"
          onClick={onCreateChat}
          aria-label={t('shell.newChat')}
          title={t('shell.newChat')}
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-[hsl(var(--sidebar-muted))] transition-colors hover:bg-[hsl(var(--sidebar-tool-hover))] hover:text-[hsl(var(--sidebar-active-foreground))] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--sidebar-ring)/0.18)]"
        >
          <Plus className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
};

export default PersonaHeader;
