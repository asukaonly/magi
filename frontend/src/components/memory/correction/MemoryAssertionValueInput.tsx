import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';

interface MemoryAssertionValueInputProps {
  id: string;
  value: string;
  valueOptions?: readonly string[] | null;
  disabled?: boolean;
  invalid?: boolean;
  errorMessageId?: string;
  maxLength?: number;
  onChange: (value: string) => void;
}

/** Keep the API's semantic values separate from the labels shown in the editor. */
export function MemoryAssertionValueInput({
  id,
  value,
  valueOptions,
  disabled,
  invalid,
  errorMessageId,
  maxLength = 2000,
  onChange,
}: MemoryAssertionValueInputProps) {
  const { t } = useTranslation('app');
  if (!valueOptions) {
    return (
      <Input
        id={id}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        maxLength={maxLength}
        aria-invalid={invalid}
        aria-errormessage={errorMessageId}
        className="h-11"
      />
    );
  }

  return (
    <select
      id={id}
      value={value}
      disabled={disabled || valueOptions.length === 0}
      onChange={(event) => onChange(event.target.value)}
      aria-invalid={invalid}
      aria-errormessage={errorMessageId}
      className="h-11 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      {!valueOptions.includes(value) ? (
        <option value={value} disabled>
          {t('memory.correction.values.unavailable')}
        </option>
      ) : null}
      {valueOptions.map((option) => (
        <option key={option} value={option}>
          {t(`memory.correction.values.${option}`, {
            defaultValue: t('memory.correction.values.unavailable'),
          })}
        </option>
      ))}
    </select>
  );
}
