import { useTranslation } from 'react-i18next';
import type { UserProfileProjection } from '@/api/modules/profile';

interface ProfileFieldSourceProps {
  profile: UserProfileProjection | null;
  fieldKey: string;
}

/** Source keys with a user-facing label; anything else is an internal detail
 * and stays hidden. */
const KNOWN_SOURCES = new Set(['settings_profile', 'chat', 'derived', 'user_authored']);

/** Renders the provenance label for a profile field (e.g. "来源：对话记忆"). */
export function ProfileFieldSource({ profile, fieldKey }: ProfileFieldSourceProps) {
  const { t } = useTranslation('app');
  const source = profile?.field_sources?.[fieldKey];
  if (!source || typeof source !== 'object') {
    return null;
  }
  const record = source as Record<string, unknown>;
  const sourceLabel = String(record.source || '');
  if (!KNOWN_SOURCES.has(sourceLabel)) {
    return null;
  }
  return (
    <span className="text-[11px] leading-5 text-[hsl(var(--memory-muted))]">
      {t('memory.portrait.identity.source', {
        source: t(`memory.portrait.identity.sources.${sourceLabel}`),
      })}
    </span>
  );
}

export default ProfileFieldSource;
