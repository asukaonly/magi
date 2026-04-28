import { useTranslation } from 'react-i18next';

export function LLMProviderImageModelFields() {
  const { t } = useTranslation('onboarding');

  return (
    <div className="space-y-3">
      <p className="rounded-xl bg-background/80 px-3 py-3 text-sm text-muted-foreground">
        {t('llm.modelFields.imageRuntimeHint')}
      </p>
      <ul className="grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
        <li className="rounded-lg bg-background/60 px-3 py-2">
          <span className="block text-xs font-medium text-foreground">{t('llm.modelFields.imageSizes')}</span>
          <span>1024×1024 / 1024×1536 / 1536×1024 / auto</span>
        </li>
        <li className="rounded-lg bg-background/60 px-3 py-2">
          <span className="block text-xs font-medium text-foreground">{t('llm.modelFields.imageQuality')}</span>
          <span>auto / high / medium / low</span>
        </li>
      </ul>
    </div>
  );
}