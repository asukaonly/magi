import React, { useEffect, useMemo, useState } from 'react';
import { SimpleForm as Form } from './simple-form';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { useNavigate } from 'react-router-dom';
import { configApi } from '../../api/modules/config';
import type { SystemConfig } from '../../api/modules/config';
import LanguageForm from '../config-forms/LanguageForm';
import LLMForm from '../config-forms/LLMForm';
import PersonalityForm from '../config-forms/PersonalityForm';
import MemoryForm from '../config-forms/MemoryForm';
import ToolsForm from '../config-forms/ToolsForm';
import GuidedConfigFrame from '../config-forms/GuidedConfigFrame';
import ModeSelection from './ModeSelection';
import StepIndicator from './StepIndicator';
import CompletionScreen from './CompletionScreen';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';

type Mode = 'quick' | 'expert' | null;

const STORAGE_KEY = 'magi_onboarding_state';
const BUILTIN_SCENARIOS = ['context_decider', 'core', 'embedding'] as const;
const toI18nLanguage = (language?: string): 'en' | 'zh-CN' => (language === 'en' ? 'en' : 'zh-CN');

interface OnboardingFlowProps {
  initialConfig: SystemConfig;
}

export const OnboardingFlow: React.FC<OnboardingFlowProps> = ({ initialConfig }) => {
  const { t, i18n } = useTranslation('onboarding');
  const shouldReduceMotion = useReducedMotion();
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>(initialConfig.preferences.user_mode);
  const [current, setCurrent] = useState(0);
  const [saving, setSaving] = useState(false);
  const [renderLanguage, setRenderLanguage] = useState(i18n.resolvedLanguage || i18n.language);
  const activeLanguage = i18n.resolvedLanguage || i18n.language;
  const isQuickMode = mode === 'quick';
  const debugI18n = localStorage.getItem('magi_i18n_debug') === '1';

  useEffect(() => {
    // Set initial i18n language based on form value (already set in OnboardingPage)
    const formLanguage = initialConfig.preferences?.language || 'zh';
    const configuredLanguage = toI18nLanguage(formLanguage);

    document.documentElement.lang = configuredLanguage;
    setRenderLanguage(configuredLanguage);

    if ((i18n.resolvedLanguage || i18n.language) !== configuredLanguage) {
      void i18n.changeLanguage(configuredLanguage);
    }
  }, [i18n, initialConfig.preferences?.language]);

  const steps = useMemo(() => {
    const shared = [t('steps.language'), t('steps.mode'), t('steps.llmProviders')];
    return mode === 'expert'
      ? [...shared, t('steps.llmModels'), t('steps.personality'), t('steps.memory'), t('steps.tools'), t('steps.complete')]
      : [...shared, t('steps.complete')];
  }, [mode, t, activeLanguage]);

  const isLastStep = current === steps.length - 1;

  useEffect(() => {
    const cached = localStorage.getItem(STORAGE_KEY);
    if (!cached) return;
    try {
      const parsed = JSON.parse(cached) as { current?: number; mode?: Mode; values?: SystemConfig };
      if (parsed.mode) {
        setMode(parsed.mode);
      }
      if (typeof parsed.current === 'number') {
        setCurrent(parsed.current);
      }
      if (parsed.values) {
        // Restore cached values, but prefer localStorage language setting
        const savedLanguage = localStorage.getItem('magi_language');
        const mergedValues = {
          ...parsed.values,
          preferences: {
            ...parsed.values?.preferences,
            language: savedLanguage || parsed.values?.preferences?.language,
          },
        };
        form.setFieldsValue(mergedValues);
      }
    } catch {
      // Ignore invalid cached state.
    }
  }, [form]);

  useEffect(() => {
    const language = form.getFieldValue(['preferences', 'language']);
    if (!language) {
      form.setFieldValue(['preferences', 'language'], 'zh');
    }
  }, [form]);

  const saveProgress = (values: SystemConfig) => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        current,
        mode,
        values,
      })
    );
  };

  const onValuesChange = (_: unknown, allValues: SystemConfig) => {
    const nextLanguage = allValues?.preferences?.language;
    if (nextLanguage) {
      const mapped = toI18nLanguage(nextLanguage);
      localStorage.setItem('magi_language', nextLanguage);
      document.documentElement.lang = mapped;
      if (debugI18n) {
        console.info('[onboarding:i18n] onValuesChange', {
          raw: nextLanguage,
          mapped,
          current: i18n.language,
        });
      }
      if (i18n.language !== mapped) {
        void i18n.changeLanguage(mapped);
      }
    }
    saveProgress(allValues);
  };

  useEffect(() => {
    if (!debugI18n) return;
    const handleLanguageChanged = (lng: string) => {
      console.info('[onboarding:i18n] languageChanged', { lng });
    };
    i18n.on('languageChanged', handleLanguageChanged);
    return () => {
      i18n.off('languageChanged', handleLanguageChanged);
    };
  }, [debugI18n, i18n]);
  useEffect(() => {
    const handleLanguageChanged = (lng: string) => {
      setRenderLanguage(lng);
    };
    i18n.on('languageChanged', handleLanguageChanged);
    return () => {
      i18n.off('languageChanged', handleLanguageChanged);
    };
  }, [i18n]);

  const handleFinish = async () => {
    const values = form.getFieldsValue(true);
    values.preferences.onboarding_completed = true;
    await configApi.completeOnboarding(values);
    localStorage.removeItem(STORAGE_KEY);
    if (values.preferences.language) {
      localStorage.setItem('magi_language', values.preferences.language);
    }
    if (values.preferences.language !== initialConfig.preferences.language) {
      window.location.href = '/';
      return;
    }
    navigate('/');
  };

  const hasEnabledProvider = (): boolean => {
    const llmConfig = form.getFieldValue(['llm']);
    return Object.values(llmConfig?.providers || {}).some((provider: any) => provider?.enabled);
  };

  const validateProviderFields = (): { valid: boolean; message?: string } => {
    const llmConfig = form.getFieldValue(['llm']);
    const providers = llmConfig?.providers || {};

    for (const [providerId, provider] of Object.entries(providers) as [string, any][]) {
      if (!provider?.enabled) continue;

      // Custom provider: all fields required
      if (provider.provider_type === 'custom') {
        if (!provider.display_name?.trim()) {
          return { valid: false, message: t('llm.validation.customProviderNameRequired') };
        }
        if (!provider.api_key?.trim()) {
          return { valid: false, message: t('llm.validation.customProviderApiKeyRequired') };
        }
        if (!provider.base_url?.trim()) {
          return { valid: false, message: t('llm.validation.customProviderBaseUrlRequired') };
        }
        // At least one model required for custom provider
        if (!provider.custom_models?.length) {
          return { valid: false, message: t('llm.validation.customProviderModelRequired') };
        }
      } else {
        // Built-in provider: API key required
        if (!provider.api_key?.trim()) {
          return { valid: false, message: t('llm.validation.apiKeyRequired', { provider: provider.display_name || providerId }) };
        }
      }
    }

    return { valid: true };
  };

  const hasValidSelections = (): boolean => {
    const llmConfig = form.getFieldValue(['llm']);
    return BUILTIN_SCENARIOS.every((scenario) => {
      const selection = llmConfig?.selections?.[scenario];
      return Boolean(
        selection?.provider_id &&
        selection?.model &&
        llmConfig?.providers?.[selection.provider_id]?.enabled
      );
    });
  };

  const handleNext = async () => {
    if (current === 0) {
      const selectedLanguage = form.getFieldValue(['preferences', 'language']) || 'zh';
      form.setFieldValue(['preferences', 'language'], selectedLanguage);

      setSaving(true);
      try {
        localStorage.setItem('magi_language', selectedLanguage);
        document.documentElement.lang = toI18nLanguage(selectedLanguage);
        void i18n.changeLanguage(toI18nLanguage(selectedLanguage));

        saveProgress(form.getFieldsValue(true));
        setCurrent(1);
      } finally {
        setSaving(false);
      }
      return;
    }

    if (current === 1) {
      if (!mode) {
        toast.warning(t('messages.chooseModeFirst'));
        return;
      }
      setSaving(true);
      try {
        saveProgress(form.getFieldsValue(true));
        setCurrent(2);
      } finally {
        setSaving(false);
      }
      return;
    }

    try {
      setSaving(true);
      await form.validateFields();

      if (current === 2 && !hasEnabledProvider()) {
        toast.warning(t('llm.providerConfiguration.enableProviderFirst'));
        return;
      }

      // Validate provider fields when moving from providers step
      if (current === 2) {
        const validation = validateProviderFields();
        if (!validation.valid) {
          toast.warning(validation.message || t('messages.validationFailed'));
          return;
        }
      }

      if (!isQuickMode && current === 3 && !hasValidSelections()) {
        toast.warning(t('llm.completeSelections'));
        return;
      }

      if (isLastStep) {
        await handleFinish();
      } else {
        setCurrent((prev) => prev + 1);
      }
    } catch (error: any) {
      if (error?.errorFields?.length) {
        // Inline field errors are already displayed by SimpleForm.
      } else {
        toast.error(error?.message || t('messages.saveFailed'));
      }
    } finally {
      setSaving(false);
    }
  };

  const handlePrev = () => setCurrent((prev) => Math.max(0, prev - 1));

  const renderStepContent = () => {
    if (current === 0) {
      return <LanguageForm includeMode={false} />;
    }

    if (current === 1) {
      return (
        <ModeSelection
          value={mode}
          onChange={(nextMode) => {
            setMode(nextMode);
            form.setFieldValue(['preferences', 'user_mode'], nextMode);
            saveProgress(form.getFieldsValue(true));
            setCurrent(2);
          }}
        />
      );
    }

    if (!mode) {
      return <div className="text-muted-foreground">{t('messages.chooseModeFirst')}</div>;
    }

    const language = form.getFieldValue(['preferences', 'language']) || 'zh';
    const quickSteps = [2, 3];
    const expertSteps = [2, 3, 4, 5, 6, 7];

    if (isQuickMode && current === quickSteps[0]) return <LLMForm quickMode view="providers" />;
    if (isQuickMode && current === quickSteps[1]) return <CompletionScreen onFinish={handleFinish} />;

    if (!isQuickMode && current === expertSteps[0]) return <LLMForm quickMode={false} view="providers" />;
    if (!isQuickMode && current === expertSteps[1]) return <LLMForm quickMode={false} view="models" />;
    if (!isQuickMode && current === expertSteps[2]) return <PersonalityForm quickMode={false} language={language} />;
    if (!isQuickMode && current === expertSteps[3]) return <MemoryForm />;
    if (!isQuickMode && current === expertSteps[4]) return <ToolsForm />;
    if (!isQuickMode && current === expertSteps[5]) return <CompletionScreen onFinish={handleFinish} />;

    return null;
  };

  return (
    <GuidedConfigFrame
      className="h-[clamp(620px,82vh,840px)]"
      layoutClassName="h-full"
      sidebarClassName="lg:w-44"
      sidebar={<StepIndicator steps={steps} current={current} />}
      footer={(
        <div className="flex items-center justify-between gap-3">
          <Button variant="outline" onClick={handlePrev} disabled={current === 0}>
            {t('actions.previous')}
          </Button>
          <Button onClick={handleNext} disabled={saving}>
            {saving ? t('actions.saving') : isLastStep ? t('actions.finish') : t('actions.next')}
          </Button>
        </div>
      )}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={initialConfig}
        onValuesChange={onValuesChange}
      >
        <AnimatePresence mode="wait">
          <motion.div
            key={`${renderLanguage}-${mode ?? 'none'}-${current}`}
            initial={shouldReduceMotion ? false : { opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={shouldReduceMotion ? undefined : { opacity: 0, x: -24 }}
            transition={{ duration: shouldReduceMotion ? 0 : 0.22, ease: 'easeOut' }}
          >
            {renderStepContent()}
          </motion.div>
        </AnimatePresence>
      </Form>
    </GuidedConfigFrame>
  );
};

export default OnboardingFlow;
