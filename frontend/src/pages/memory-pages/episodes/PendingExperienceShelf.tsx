import { useTranslation } from 'react-i18next';
import {
  CalendarRange,
  CheckCircle2,
  CircleSlash2,
  Layers,
  Loader2,
  Sparkles,
} from 'lucide-react';
import type { L2ExperienceSeed } from '@/api/modules/memory';
import { formatMemoryTimeRange } from '@/utils/memory-time';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  getSeedDescription,
  getSeedTags,
  getSeedTitle,
} from './experienceIndexModel';

export function PendingExperienceShelf({
  seeds,
  actionId,
  onPromote,
  onReject,
}: {
  seeds: L2ExperienceSeed[];
  actionId: string | null;
  onPromote: (seedId: string) => Promise<void>;
  onReject: (seedId: string) => Promise<void>;
}) {
  const { t } = useTranslation('app');

  return (
    <section className="space-y-3">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-[hsl(var(--memory-title))]">
            {t('memory.episodes.pending.title')}
          </h2>
          <p className="mt-1 text-xs text-[hsl(var(--memory-muted))]">
            {t('memory.episodes.pending.subtitle')}
          </p>
        </div>
        <Badge variant="outline" className="w-fit rounded-full border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.78)] text-[hsl(var(--memory-muted))]">
          {t('memory.episodes.pending.count', { count: seeds.length })}
        </Badge>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        {seeds.slice(0, 3).map((seed) => (
          <PendingExperienceCard
            key={seed.seed_id}
            seed={seed}
            actionId={actionId}
            onPromote={onPromote}
            onReject={onReject}
          />
        ))}
      </div>
    </section>
  );
}

function PendingExperienceCard({
  seed,
  actionId,
  onPromote,
  onReject,
}: {
  seed: L2ExperienceSeed;
  actionId: string | null;
  onPromote: (seedId: string) => Promise<void>;
  onReject: (seedId: string) => Promise<void>;
}) {
  const { t, i18n } = useTranslation('app');
  const tags = getSeedTags(seed, 3);
  const title = getSeedTitle(seed, t('memory.episodes.pending.fallbackTitle'));
  const description = getSeedDescription(
    seed,
    tags,
    t('memory.episodes.pending.fallbackDescription'),
    t('memory.episodes.pending.fallbackDescriptionGeneric')
  );
  const range = formatMemoryTimeRange(seed.time_start, seed.time_end, i18n.language);
  const promoting = actionId === `${seed.seed_id}:promote`;
  const rejecting = actionId === `${seed.seed_id}:reject`;
  const busy = promoting || rejecting;

  return (
    <article className="flex min-h-[176px] flex-col justify-between rounded-lg border border-[hsl(var(--memory-border)/0.58)] bg-[hsl(var(--memory-panel-elevated)/0.82)] p-4 shadow-[0_10px_28px_hsl(var(--memory-shadow)/0.04)]">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
          <Sparkles className="h-3.5 w-3.5 text-[hsl(var(--memory-accent))]" aria-hidden="true" />
          <span>{t('memory.episodes.pending.clearSignal')}</span>
        </div>
        <h3 className="mt-2 line-clamp-2 text-base font-semibold leading-6 text-[hsl(var(--memory-title))]">
          {title}
        </h3>
        <p className="mt-2 line-clamp-2 text-sm leading-6 text-[hsl(var(--memory-body))]">
          {description}
        </p>
      </div>

      <div className="mt-4 space-y-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs text-[hsl(var(--memory-muted))]">
          {range ? (
            <span className="inline-flex min-w-0 items-center gap-1">
              <CalendarRange className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              <span className="truncate">{range}</span>
            </span>
          ) : null}
          <span className="inline-flex items-center gap-1">
            <Layers className="h-3.5 w-3.5" aria-hidden="true" />
            {t('memory.episodes.pending.evidenceCount', { count: seed.evidence_count ?? 0 })}
          </span>
        </div>
        {tags.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {tags.map((tag) => (
              <span key={tag} className="rounded-md bg-[hsl(var(--memory-panel-subtle)/0.82)] px-2 py-1 text-xs text-[hsl(var(--memory-body))]">
                {tag}
              </span>
            ))}
          </div>
        ) : null}
        <div className="flex flex-wrap gap-2 pt-1">
          <Button
            type="button"
            size="sm"
            className="h-8 rounded-lg bg-[hsl(var(--memory-accent))] px-3 text-xs text-[hsl(var(--memory-accent-foreground))] hover:bg-[hsl(var(--memory-accent)/0.9)]"
            disabled={busy}
            onClick={() => { void onPromote(seed.seed_id); }}
          >
            {promoting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {t('memory.episodes.pending.actions.promote')}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 rounded-lg px-3 text-xs"
            disabled={busy}
            onClick={() => { void onReject(seed.seed_id); }}
          >
            {rejecting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <CircleSlash2 className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {t('memory.episodes.pending.actions.reject')}
          </Button>
        </div>
      </div>
    </article>
  );
}
