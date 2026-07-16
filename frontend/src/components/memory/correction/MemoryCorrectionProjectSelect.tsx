import { Loader2, Search } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { MemoryCorrectionContextOption } from '@/api/modules/memory';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface MemoryCorrectionProjectSelectProps {
  options: readonly MemoryCorrectionContextOption[];
  value: string;
  onChange: (contextId: string) => void;
  loading: boolean;
  loadError: boolean;
  onRetry: () => void;
  validationError?: string | null;
  submitted: boolean;
}

export function MemoryCorrectionProjectSelect({
  options,
  value,
  onChange,
  loading,
  loadError,
  onRetry,
  validationError,
  submitted,
}: MemoryCorrectionProjectSelectProps) {
  const { t } = useTranslation('app');
  const [query, setQuery] = useState('');
  useEffect(() => {
    setQuery('');
  }, [options]);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const selected = options.find((option) => option.context_id === value);
  const matches = useMemo(
    () => options.filter((option) => (
      !normalizedQuery || option.label.toLocaleLowerCase().includes(normalizedQuery)
    )),
    [normalizedQuery, options]
  );
  const visibleOptions = selected && !matches.some((option) => option.context_id === selected.context_id)
    ? [selected, ...matches]
    : matches;

  return (
    <fieldset>
      <legend className="text-sm font-semibold text-foreground">
        {t('memory.correction.scopeLabel', { defaultValue: '适用于哪个项目？' })}
      </legend>
      <p className="mt-1 text-xs leading-5 text-muted-foreground">
        {t('memory.correction.projectHint', {
          defaultValue: '只会在你选择的项目里使用这条记忆。项目来自已连接的工作区。',
        })}
      </p>

      {loading ? (
        <div className="mt-3 flex min-h-11 items-center gap-2 rounded-lg border border-border/70 px-3 text-sm text-muted-foreground" role="status">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          {t('memory.correction.projectLoading', { defaultValue: '正在读取可选项目…' })}
        </div>
      ) : loadError ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm leading-5 text-amber-800 dark:bg-amber-950/30 dark:text-amber-200" role="alert">
          <span>{t('memory.correction.projectLoadFailed', { defaultValue: '暂时无法读取项目列表。' })}</span>
          <Button
            id="memory-correction-project-retry"
            type="button"
            size="sm"
            variant="ghost"
            className="min-h-10"
            onClick={onRetry}
          >
            {t('memory.correction.projectRetry', { defaultValue: '重试' })}
          </Button>
        </div>
      ) : options.length === 0 ? (
        <div
          id="memory-correction-project-empty"
          role="status"
          tabIndex={-1}
          className="mt-3 rounded-lg bg-muted/55 px-3 py-3 text-sm leading-6 text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t('memory.correction.projectEmpty', {
            defaultValue: '还没有可选项目。先连接一个工作区后，再限定这条记忆的适用范围。',
          })}
        </div>
      ) : (
        <div className="mt-3 space-y-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input
              id="memory-correction-project-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              maxLength={200}
              aria-label={t('memory.correction.projectSearch', { defaultValue: '搜索项目' })}
              placeholder={t('memory.correction.projectSearchPlaceholder', { defaultValue: '按项目名称搜索' })}
              className="h-11 pl-9"
            />
          </div>
          <label htmlFor="memory-correction-scope-context" className="sr-only">
            {t('memory.correction.projectSelect', { defaultValue: '选择项目' })}
          </label>
          <select
            id="memory-correction-scope-context"
            value={value}
            onChange={(event) => onChange(event.target.value)}
            aria-invalid={Boolean(submitted && validationError)}
            aria-errormessage={validationError ? 'memory-correction-scope-context-error' : undefined}
            className="h-11 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <option value="">
              {t('memory.correction.projectSelectPlaceholder', { defaultValue: '请选择一个项目' })}
            </option>
            {visibleOptions.map((option) => (
              <option key={option.context_id} value={option.context_id}>{option.label}</option>
            ))}
          </select>
          {normalizedQuery && matches.length === 0 ? (
            <p className="text-xs leading-5 text-muted-foreground" role="status">
              {t('memory.correction.projectNoMatches', { defaultValue: '没有找到匹配的项目。' })}
            </p>
          ) : null}
        </div>
      )}

      {validationError ? (
        <p id="memory-correction-scope-context-error" className="mt-2 text-xs leading-5 text-destructive">
          {validationError}
        </p>
      ) : null}
    </fieldset>
  );
}

export default MemoryCorrectionProjectSelect;
