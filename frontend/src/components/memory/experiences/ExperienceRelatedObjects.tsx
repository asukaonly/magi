import type { ReactNode } from 'react';
import { MapPin, Tags, UserRound } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function RelatedObjectsPanel({
  entities,
  places,
  topics,
}: {
  entities: string[];
  places: string[];
  topics: string[];
}) {
  const { t } = useTranslation('app');
  return (
    <section className="rounded-lg border border-[hsl(var(--memory-border)/0.42)] bg-[hsl(var(--memory-panel-elevated)/0.5)] px-5 py-4">
      <div className="grid gap-4 md:grid-cols-3">
        <TagGroup
          icon={<UserRound className="h-4 w-4" aria-hidden="true" />}
          title={t('memory.episodes.sections.entities')}
          values={entities}
        />
        <TagGroup
          icon={<MapPin className="h-4 w-4" aria-hidden="true" />}
          title={t('memory.episodes.sections.places')}
          values={places}
        />
        <TagGroup
          icon={<Tags className="h-4 w-4" aria-hidden="true" />}
          title={t('memory.episodes.sections.topics')}
          values={topics}
        />
      </div>
    </section>
  );
}

function TagGroup({ icon, title, values }: { icon: ReactNode; title: string; values: string[] }) {
  const { t } = useTranslation('app');
  return (
    <section className="min-w-0">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-[hsl(var(--memory-title))]">
        <span className="text-[hsl(var(--memory-accent))]">{icon}</span>
        {title}
      </h3>
      <div className="mt-3 flex flex-wrap gap-2">
        {values.length > 0 ? values.map((value) => (
          <span key={value} className="min-w-0 rounded-md border border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.82)] px-2 py-1 text-xs text-[hsl(var(--memory-body))]">
            {value}
          </span>
        )) : (
          <span className="text-sm text-[hsl(var(--memory-muted))]">{t('memory.episodes.noTags')}</span>
        )}
      </div>
    </section>
  );
}
