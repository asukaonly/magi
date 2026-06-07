import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { usePluginInstallPanelStore } from '@/stores/pluginInstallPanel';
import { listInstallable, type InstallableItem } from '@/api/modules/systemSuggestions';
import { PRODUCT_TOUR_STEPS, pickZeroConfigSource } from './productTourSteps';

/** "netease-music" → "Netease Music" — readable fallback when a plugin has no
 *  localized name in the `pluginNames` i18n map. */
function humanizePluginId(pluginId: string): string {
  return pluginId
    .split(/[-_]/)
    .filter(Boolean)
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(' ');
}

export interface ProductTourProps {
  /** Called when the tour completes OR is skipped (mark flag + fire bootstrap). */
  onComplete: () => void;
}

function useTargetRect(testId: string): DOMRect | null {
  const [rect, setRect] = useState<DOMRect | null>(null);
  useEffect(() => {
    const measure = () => {
      const el = document.querySelector(`[data-testid="${testId}"]`);
      setRect(el ? el.getBoundingClientRect() : null);
    };
    measure();
    window.addEventListener('resize', measure);
    const id = window.setInterval(measure, 300); // cheap re-measure for layout settle
    return () => {
      window.removeEventListener('resize', measure);
      window.clearInterval(id);
    };
  }, [testId]);
  return rect;
}

export function ProductTour({ onComplete }: ProductTourProps): JSX.Element | null {
  const { t } = useTranslation('app');
  const [index, setIndex] = useState(0);
  const [source, setSource] = useState<InstallableItem | null>(null);
  const doneRef = useRef(false);
  const step = PRODUCT_TOUR_STEPS[index];
  const rect = useTargetRect(step?.targetTestId ?? '');

  useEffect(() => {
    void listInstallable()
      .then((items) => setSource(pickZeroConfigSource(items)))
      .catch(() => setSource(null));
  }, []);

  // Connect opens the single MainLayout-mounted <PluginInstallPanel>, which owns
  // the full honest flow (install → enable → sync → build-memory). The tour just
  // triggers it and lets the user keep going.
  const openPanel = usePluginInstallPanelStore((s) => s.openPanel);

  const finish = useCallback(() => {
    if (doneRef.current) return;
    doneRef.current = true;
    onComplete();
  }, [onComplete]);

  const isLast = index >= PRODUCT_TOUR_STEPS.length - 1;
  const next = () => (isLast ? finish() : setIndex((i) => i + 1));
  const back = () => setIndex((i) => Math.max(0, i - 1));

  if (!step) return null;

  // Tooltip position: below the target, clamped to viewport.
  const top = rect ? Math.min(rect.bottom + 12, window.innerHeight - 220) : window.innerHeight / 2;
  const left = rect
    ? Math.min(Math.max(rect.left, 12), window.innerWidth - 332)
    : window.innerWidth / 2 - 160;

  const needsInstall = source ? !source.installed : false;
  const connectLabel = needsInstall
    ? t('productTour.installAndConnect')
    : t('productTour.connect');

  return (
    <div className="fixed inset-0 z-[60]" role="dialog" aria-label={t(step.titleKey)}>
      <div className="absolute inset-0 bg-black/40" />
      {rect ? (
        <div
          aria-hidden
          className="pointer-events-none absolute rounded-lg ring-2 ring-primary ring-offset-2 transition-all"
          style={{ top: rect.top - 4, left: rect.left - 4, width: rect.width + 8, height: rect.height + 8 }}
        />
      ) : null}
      <div
        className="absolute w-[320px] rounded-lg border border-border/55 bg-card p-4 shadow-xl"
        style={{ top, left }}
      >
        <h3 className="text-sm font-medium text-foreground">{t(step.titleKey)}</h3>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{t(step.bodyKey)}</p>
        {step.connect && source ? (
          <div className="mt-3">
            {/* Name the plugin so the user knows WHAT they're installing (the
                bare "安装并启用" gave no clue). Localized via pluginNames, humanized fallback. */}
            <p className="text-xs font-medium text-foreground">
              {t('productTour.recommend', {
                plugin: t(`pluginNames.${source.plugin_id}`, {
                  ns: 'onboarding',
                  defaultValue: humanizePluginId(source.plugin_id),
                }),
              })}
            </p>
            <button
              type="button"
              data-testid={`tour-connect-${source.plugin_id}`}
              onClick={() => openPanel(source.plugin_id, { install: needsInstall })}
              className="mt-1.5 rounded-md border border-primary/40 px-3 py-1.5 text-xs font-medium text-primary transition hover:bg-primary/10 disabled:opacity-50"
            >
              {connectLabel}
            </button>
          </div>
        ) : null}
        <div className="mt-3 flex items-center justify-between">
          <button
            type="button"
            onClick={finish}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            {t('productTour.skip')}
          </button>
          <div className="flex items-center gap-2">
            {index > 0 ? (
              <button
                type="button"
                onClick={back}
                className="rounded-md px-2.5 py-1 text-xs text-muted-foreground hover:text-foreground"
              >
                {t('productTour.back')}
              </button>
            ) : null}
            <button
              type="button"
              onClick={next}
              className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            >
              {isLast ? t('productTour.done') : t('productTour.next')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ProductTour;
