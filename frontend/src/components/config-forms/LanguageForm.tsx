import React from 'react';
import { useTranslation } from 'react-i18next';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { cn } from '@/lib/utils';

interface LanguageFormProps {
  includeMode?: boolean;
}

const selectableStyle = (active: boolean): string =>
  cn(
    'rounded-xl border bg-background p-4 text-left transition cursor-pointer',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-600/60',
    active ? 'border-primary-600 bg-primary-600/5 shadow-sm' : 'border-border hover:border-primary-500/40'
  );

const languages = [
  { value: 'zh', labelKey: 'language.zhHans', description: 'Simplified Chinese' },
  { value: 'en', labelKey: 'language.en', description: 'English' },
] as const;

export const LanguageForm: React.FC<LanguageFormProps> = ({ includeMode = true }) => {
  const { t } = useTranslation('onboarding');

  return (
    <div className="space-y-6">
      <div>
        <h3 className="mb-1 text-base font-medium">{t('language.label')}</h3>
        <p className="mb-4 text-sm text-muted-foreground">{t('language.description')}</p>
      </div>

      <Form.Item shouldUpdate noStyle>
        {({
          getFieldValue,
          setFieldValue,
        }: {
          getFieldValue: (name: any) => any;
          setFieldValue: (name: any, value: any) => void;
        }) => {
          const currentLanguage = getFieldValue(['preferences', 'language']) || 'zh';

          return (
            <div className="grid grid-cols-2 gap-3">
              {languages.map((lang) => (
                <button
                  key={lang.value}
                  type="button"
                  onClick={() => setFieldValue(['preferences', 'language'], lang.value)}
                  className={selectableStyle(currentLanguage === lang.value)}
                >
                  <div className="flex items-center gap-3">
                    <div className={cn(
                      'flex h-10 w-10 items-center justify-center rounded-lg text-lg font-medium',
                      currentLanguage === lang.value ? 'bg-primary-600/10 text-primary-600' : 'bg-muted text-muted-foreground'
                    )}>
                      {lang.value === 'zh' ? 'Zh' : 'En'}
                    </div>
                    <div>
                      <div className="font-medium">{t(lang.labelKey)}</div>
                      <div className="text-xs text-muted-foreground">{lang.description}</div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          );
        }}
      </Form.Item>

      {includeMode && (
        <Form.Item label={t('mode.label')} name={['preferences', 'user_mode']}>
          <input type="text" className="hidden" />
        </Form.Item>
      )}
    </div>
  );
};

export default LanguageForm;
