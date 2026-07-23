import React, { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, File, FolderOpen, Plus, X } from 'lucide-react';

import { SelectField } from '@/components/config-forms/fields';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { normalizeDynamicSpec, type DynamicConfigSpec } from '@/components/config-forms/dynamic-config-specs';
import { pickDirectory, pickFile } from '@/runtime/desktop';

interface DynamicConfigFieldProps {
  spec: DynamicConfigSpec;
  value: any;
  onChange: (value: any) => void;
  disabled?: boolean;
  providerName?: string;
  selectOptions?: Array<{ label: string; value: string; disabled?: boolean }>;
}

export const DynamicConfigField: React.FC<DynamicConfigFieldProps> = ({
  spec,
  value,
  onChange,
  disabled = false,
  providerName,
  selectOptions,
}) => {
  const { t } = useTranslation('app');
  const [showPassword, setShowPassword] = useState(false);
  const [tagInput, setTagInput] = useState('');
  const normalized = normalizeDynamicSpec(spec, providerName);

  const handleChange = useCallback(
    (newValue: any) => {
      if (!disabled) {
        onChange(newValue);
      }
    },
    [disabled, onChange]
  );

  const renderLabel = () => (
    <span className="text-sm font-medium">
      {normalized.label}
      {normalized.required ? <span className="ml-1 text-destructive">*</span> : null}
    </span>
  );

  const renderField = () => {
    if (normalized.inputKind === 'boolean') {
      return (
        <label className="flex items-center justify-between">
          {renderLabel()}
          <Switch
            checked={!!value}
            onCheckedChange={handleChange}
            disabled={disabled || normalized.readOnly}
          />
        </label>
      );
    }

    if (normalized.inputKind === 'select') {
      const options = selectOptions ?? (normalized.enumValues || []).map((item) => ({
        label: String(item),
        value: String(item),
      }));

      return (
        <label className="space-y-2">
          {renderLabel()}
          <SelectField
            value={String(value ?? normalized.defaultValue ?? '')}
            onChange={handleChange}
            options={options}
            placeholder={normalized.placeholder || t('settings.selectPlaceholder')}
            disabled={disabled || normalized.readOnly}
            allowEmpty={!normalized.required}
          />
        </label>
      );
    }

    if (normalized.inputKind === 'secret') {
      const sensitivePlaceholder = value ? '•••••••••' : undefined;
      return (
        <label className="space-y-2">
          {renderLabel()}
          <div className="relative">
            <Input
              type={showPassword ? 'text' : 'password'}
              value={value ?? ''}
              onChange={(event) => handleChange(event.target.value)}
              placeholder={normalized.placeholder || sensitivePlaceholder}
              disabled={disabled || normalized.readOnly}
              className="pr-10"
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label={showPassword ? t('settings.hideSensitiveValue') : t('settings.showSensitiveValue')}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </label>
      );
    }

    if (normalized.inputKind === 'number') {
      return (
        <label className="space-y-2">
          {renderLabel()}
          <input
            type="number"
            value={value ?? normalized.defaultValue ?? ''}
            onChange={(event) => handleChange(event.target.value === '' ? '' : Number(event.target.value))}
            placeholder={normalized.placeholder}
            disabled={disabled || normalized.readOnly}
            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
          />
        </label>
      );
    }

    if (normalized.inputKind === 'path') {
      const selectedPath = typeof value === 'string' ? value : '';
      const isDirectory = normalized.pathKind === 'directory';
      const browseLabel = t(isDirectory ? 'settings.browseFolder' : 'settings.browseFile');
      const emptyLabel = t(isDirectory ? 'settings.noFolderSelected' : 'settings.noFileSelected');
      const clearLabel = t(
        isDirectory ? 'settings.clearFolderSelection' : 'settings.clearFileSelection',
      );
      const PathIcon = isDirectory ? FolderOpen : File;
      const handleBrowse = async () => {
        try {
          const selected = isDirectory
            ? await pickDirectory(selectedPath || undefined)
            : await pickFile(selectedPath || undefined);
          if (selected) {
            handleChange(selected);
          }
        } catch {
          // Native browsing is unavailable outside the desktop runtime.
        }
      };

      return (
        <div className="space-y-2">
          {renderLabel()}
          <div className="flex min-w-0 gap-2">
            <button
              type="button"
              onClick={handleBrowse}
              disabled={disabled || normalized.readOnly}
              aria-label={`${normalized.label}: ${browseLabel}`}
              className="flex h-10 min-w-0 flex-1 items-center gap-2 rounded-md border border-input bg-background px-3 text-left text-sm transition-colors hover:border-primary/60 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <PathIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span
                className={selectedPath ? 'min-w-0 flex-1 truncate' : 'min-w-0 flex-1 text-muted-foreground'}
                title={selectedPath || undefined}
              >
                {selectedPath || emptyLabel}
              </span>
              <span className="shrink-0 text-xs font-medium text-primary">
                {browseLabel}
              </span>
            </button>
            {selectedPath && !normalized.required && !disabled && !normalized.readOnly ? (
              <button
                type="button"
                onClick={() => handleChange('')}
                aria-label={`${normalized.label}: ${clearLabel}`}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-input text-muted-foreground transition-colors hover:border-destructive/50 hover:text-destructive"
              >
                <X className="h-4 w-4" />
              </button>
            ) : null}
          </div>
        </div>
      );
    }

    if (normalized.inputKind === 'string') {
      return (
        <label className="space-y-2">
          {renderLabel()}
          <Input
            value={value ?? ''}
            onChange={(event) => handleChange(event.target.value)}
            placeholder={normalized.placeholder}
            disabled={disabled || normalized.readOnly}
          />
        </label>
      );
    }

    if (normalized.inputKind === 'path_list') {
      const paths: string[] = Array.isArray(value) ? value : [];
      const handleBrowse = async () => {
        try {
          // runtime/desktop is already in the eagerly-loaded bundle (via
          // main.tsx); the dynamic import previously here only produced a
          // Vite/Rolldown ineffective-dynamic-import warning. The Tauri
          // runtime check inside pickDirectory still returns undefined when
          // not running under the desktop shell.
          const selected = await pickDirectory(paths[paths.length - 1] ?? undefined);
          if (selected && !paths.includes(selected)) {
            handleChange([...paths, selected]);
          }
        } catch {
          // Not in Tauri runtime, so browsing is unavailable.
        }
      };
      const handleRemove = (index: number) => {
        handleChange(paths.filter((_, itemIndex) => itemIndex !== index));
      };
      return (
        <div className="space-y-2">
          {renderLabel()}
          {paths.length > 0 && (
            <div className="space-y-1.5">
              {paths.map((path, index) => (
                <div key={index} className="flex items-center gap-2 rounded-md border border-input bg-background px-3 py-1.5 text-sm">
                  <FolderOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="flex-1 truncate" title={path}>{path}</span>
                  {!disabled && !normalized.readOnly && (
                    <button
                      type="button"
                      onClick={() => handleRemove(index)}
                      className="shrink-0 text-muted-foreground hover:text-destructive"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
          {!disabled && !normalized.readOnly && (
            <button
              type="button"
              onClick={handleBrowse}
              className="flex items-center gap-1.5 rounded-md border border-dashed border-input px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
            >
              <Plus className="h-3.5 w-3.5" />
              {normalized.placeholder || t('settings.browseFolder')}
            </button>
          )}
        </div>
      );
    }

    if (normalized.inputKind === 'checkbox_group') {
      const selected: string[] = Array.isArray(value) ? value : [];
      const options = selectOptions ?? (normalized.enumValues || []).map((optionValue) => ({
        label: String(optionValue),
        value: String(optionValue),
      }));
      const handleToggle = (optionValue: string) => {
        if (selected.includes(optionValue)) {
          handleChange(selected.filter((selectedValue) => selectedValue !== optionValue));
        } else {
          handleChange([...selected, optionValue]);
        }
      };
      return (
        <div className="space-y-2">
          {renderLabel()}
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {options.map((option) => (
              <label key={option.value} className="flex cursor-pointer items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selected.includes(option.value)}
                  onChange={() => handleToggle(option.value)}
                  disabled={disabled || normalized.readOnly}
                  className="h-4 w-4 rounded border-input accent-primary"
                />
                {option.label}
              </label>
            ))}
          </div>
        </div>
      );
    }

    if (normalized.inputKind === 'array') {
      const tags: string[] = Array.isArray(value) ? value : [];
      const handleAdd = () => {
        const trimmed = tagInput.trim();
        if (trimmed && !tags.includes(trimmed)) {
          handleChange([...tags, trimmed]);
        }
        setTagInput('');
      };
      const handleKeyDown = (event: React.KeyboardEvent) => {
        if (event.key === 'Enter') {
          event.preventDefault();
          handleAdd();
        }
      };
      const handleRemoveTag = (index: number) => {
        handleChange(tags.filter((_, itemIndex) => itemIndex !== index));
      };
      return (
        <div className="space-y-2">
          {renderLabel()}
          {tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {tags.map((tag, index) => (
                <span
                  key={index}
                  className="inline-flex items-center gap-1 rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground"
                >
                  {tag}
                  {!disabled && !normalized.readOnly && (
                    <button
                      type="button"
                      onClick={() => handleRemoveTag(index)}
                      className="text-muted-foreground hover:text-destructive"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </span>
              ))}
            </div>
          )}
          {!disabled && !normalized.readOnly && (
            <div className="flex gap-2">
              <Input
                value={tagInput}
                onChange={(event) => setTagInput(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={normalized.placeholder || t('settings.arrayPlaceholder')}
                className="flex-1"
              />
              <button
                type="button"
                onClick={handleAdd}
                disabled={!tagInput.trim()}
                className="flex items-center gap-1 rounded-md border border-input px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      );
    }

    return (
      <label className="space-y-2">
        {renderLabel()}
        <textarea
          value={typeof value === 'object' ? JSON.stringify(value, null, 2) : ''}
          onChange={(event) => {
            try {
              const parsed = JSON.parse(event.target.value);
              handleChange(parsed);
            } catch {
              // Keep invalid JSON local until it becomes valid.
            }
          }}
          placeholder={normalized.placeholder || '{}'}
          disabled={disabled || normalized.readOnly}
          rows={3}
          className="h-20 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
        />
      </label>
    );
  };

  return (
    <div className="space-y-1.5">
      {renderField()}
      {normalized.description ? (
        <p className="text-xs leading-5 text-muted-foreground">
          {normalized.description}
        </p>
      ) : null}
    </div>
  );
};
