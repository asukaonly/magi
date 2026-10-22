import { useEffect, useState } from 'react';
import { Check, Send } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  channelEndpointsApi, endpointKey, type EndpointRef, type EndpointView,
} from '@/api/modules/channelEndpoints';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
  DropdownMenuCheckboxItem, DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu';

type Props = {
  value: EndpointRef[] | null;
  onChange: (value: EndpointRef[] | null) => void;
  disabled?: boolean;
};

export function ComposerDeliveryControl({ value, onChange, disabled = false }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [endpoints, setEndpoints] = useState<EndpointView[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!open || disabled) return;
    const controller = new AbortController();
    setLoading(true);
    setError(false);
    void channelEndpointsApi.list(controller.signal).then(items => {
      if (!controller.signal.aborted) setEndpoints(items.filter(item => item.capabilities.some(cap => cap === 'message' || cap === 'audio')));
    }).catch(() => {
      if (!controller.signal.aborted) setError(true);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [open, disabled, revision]);
  const selected = value ?? [];
  const known = new Set(endpoints.map(item => endpointKey(item.endpoint)));
  const missing = selected.filter(item => !known.has(endpointKey(item)));
  const toggle = (endpoint: EndpointRef, checked: boolean) => {
    const others = selected.filter(item => endpointKey(item) !== endpointKey(endpoint));
    onChange(checked ? [...others, endpoint] : others);
  };
  const summary = value === null ? t('chat.delivery.default')
    : value.length === 0 ? t('chat.delivery.current')
      : t('chat.delivery.selected', { count: value.length });
  return <DropdownMenu open={open && !disabled} onOpenChange={setOpen}>
    <DropdownMenuTrigger asChild>
      <button type="button" disabled={disabled}
        aria-label={t('chat.delivery.controlLabel')} title={summary}
        className="flex h-8 items-center gap-1 rounded-lg px-2 text-xs text-muted-foreground hover:bg-muted/40 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45">
        <Send className="h-4 w-4" aria-hidden="true" />
        {value !== null && <span>{summary}</span>}
      </button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="start" side="top" className="max-h-80 w-72 overflow-y-auto">
      <p className="px-2 py-2 text-xs text-muted-foreground">{t('chat.delivery.description')}</p>
      <DropdownMenuItem onSelect={() => onChange(null)}>
        <Check className={`mr-2 h-4 w-4 ${value === null ? '' : 'opacity-0'}`} />{t('chat.delivery.default')}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => onChange([])}>
        <Check className={`mr-2 h-4 w-4 ${value?.length === 0 ? '' : 'opacity-0'}`} />{t('chat.delivery.current')}
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      {loading && <p role="status" className="px-2 py-1 text-sm">{t('settings.deliveryTargets.loading')}</p>}
      {error && <DropdownMenuItem onSelect={event => { event.preventDefault(); setRevision(current => current + 1); }}>
        {t('chat.delivery.retry')}
      </DropdownMenuItem>}
      {!loading && !error && endpoints.length === 0 && <p className="px-2 py-1 text-sm">{t('settings.deliveryTargets.empty')}</p>}
      {!error && endpoints.map(item => {
        const checked = selected.some(target => endpointKey(target) === endpointKey(item.endpoint));
        return <DropdownMenuCheckboxItem key={endpointKey(item.endpoint)} checked={checked}
          disabled={loading || (!checked && selected.length >= 32)}
          onSelect={event => event.preventDefault()} onCheckedChange={enabled => toggle(item.endpoint, enabled)}>
          <span>{item.label}<span className="ml-2 text-xs text-muted-foreground">
            {t(item.available ? 'settings.deliveryTargets.available' : 'settings.deliveryTargets.unavailable')}
            {item.capabilities.includes('audio') && ` · ${t('settings.deliveryTargets.audio')}`}
          </span></span>
        </DropdownMenuCheckboxItem>;
      })}
      {!loading && missing.map(endpoint => <DropdownMenuCheckboxItem key={endpointKey(endpoint)}
        checked onSelect={event => event.preventDefault()} onCheckedChange={() => toggle(endpoint, false)}>
        {endpoint.target_id} · {t('settings.deliveryTargets.removed')}
      </DropdownMenuCheckboxItem>)}
    </DropdownMenuContent>
  </DropdownMenu>;
}
