import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ArrowLeft, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { pluginsApi, type SourceCatalogResponse } from '@/api/modules/plugins';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { usePluginInstallPanelStore, type PluginInstallDoneInfo } from '@/stores/pluginInstallPanel';
import { localizedPluginText } from '@/utils/plugin-display-groups';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { EmptyStateSourceCard } from '@/components/empty-state/EmptyStateSourceCard';
import { OnboardingScrollPane } from './OnboardingFrame';

interface Props {
  heading?: ReactNode;
  connectedPluginIds: string[];
  onBack: () => void;
  onConnectDone: (pluginId: string, info?: PluginInstallDoneInfo) => void;
}

export function AppSourceCatalog({ heading, connectedPluginIds, onBack, onConnectDone }: Props) {
  const { t, i18n } = useTranslation('onboarding');
  const [catalog, setCatalog] = useState<SourceCatalogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [query, setQuery] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);
  const beginRead = useRequestOwner();
  const openPanel = usePluginInstallPanelStore(state => state.openPanel);
  const load = useCallback(async () => {
    const isCurrent = beginRead('catalog');
    setLoading(true);
    setFailed(false);
    try {
      const result = await pluginsApi.getSourceCatalog();
      if (isCurrent()) setCatalog(result);
    } catch {
      if (isCurrent()) setFailed(true);
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [beginRead]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { searchRef.current?.focus(); }, []);
  const language = i18n.resolvedLanguage ?? i18n.language;
  const localized = (base: string, values: Record<string, string>) => localizedPluginText(base, values, language);
  const search = query.trim().toLocaleLowerCase();
  const items = (catalog?.items ?? []).filter(item =>
    item.status === 'available' || item.status === 'connected' || connectedPluginIds.includes(item.plugin_id),
  ).filter(item =>
    [item.plugin_id, item.name, localized(item.name, item.name_i18n), localized(item.description, item.description_i18n)]
      .some(text => text.toLocaleLowerCase().includes(search)),
  );
  return <section data-testid="onboarding-app-catalog" className="flex min-h-0 flex-1 flex-col">
    <OnboardingScrollPane header={<div className="space-y-4">
      {heading}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="ghost" onClick={onBack} className="-ml-3 gap-2 text-muted-foreground">
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />{t('firstContext.catalog.back')}
        </Button>
        <div className="relative w-full sm:w-64">
          <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <Input ref={searchRef} className="pl-9" value={query} onChange={event => setQuery(event.target.value)}
            aria-label={t('firstContext.catalog.search')} placeholder={t('firstContext.catalog.search')} />
        </div>
      </div>
    </div>}>
      {loading ? <p role="status" className="py-4 text-sm text-muted-foreground">{t('firstContext.catalog.loading')}</p> : null}
      {failed || catalog?.catalog_mode === 'installed_only' ? <div className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
        <span role="alert">{t(failed ? 'firstContext.catalog.failed' : 'firstContext.catalog.localOnly')}</span>
        <Button variant="ghost" onClick={() => void load()}>{t('emptyState.retry')}</Button>
      </div> : null}
      {!loading && !failed && items.length === 0 ? <p className="py-6 text-sm text-muted-foreground">{t(search ? 'firstContext.catalog.noMatches' : 'firstContext.catalog.empty')}</p> : null}
      <ul className="divide-y divide-border/50">
        {items.map(item => {
          const name = localized(item.name, item.name_i18n);
          const connected = connectedPluginIds.includes(item.plugin_id) || item.status === 'connected';
          return <li key={item.plugin_id}>
            <EmptyStateSourceCard
              pluginId={item.plugin_id} title={name} value={localized(item.description, item.description_i18n)} iconId={item.icon} variant="first_context"
              connected={connected} connectLabelKey="emptyState.connectSource"
              onConnect={() => openPanel(item.plugin_id, {
                install: !item.installed, pluginName: name, pluginIcon: item.icon,
                context: 'first_context', sourceScope: item.scope,
                onDone: info => onConnectDone(item.plugin_id, info),
              })}
            />
          </li>;
        })}
      </ul>
    </OnboardingScrollPane>
  </section>;
}
