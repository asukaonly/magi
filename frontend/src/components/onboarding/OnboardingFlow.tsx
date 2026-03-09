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
import { AnimatePresence, motion } from 'framer-motion';

type Mode = 'quick' | 'expert' | null;

const STORAGE_KEY = 'magi_onboarding_state';
const toI18nLanguage = (language?: string): 'en' | 'zh-CN' => (language === 'en' ? 'en' : 'zh-CN');

interface OnboardingFlowProps {
  initialConfig: SystemConfig;
}

export const OnboardingFlow: React.FC<OnboardingFlowProps> = ({ initialConfig }) => {
  const { t, i18n } = useTranslation('onboarding');
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>(initialConfig.preferences.user_mode);
  const [current, setCurrent] = useState(0);
  const [saving, setSaving] = useState(false);
  const [renderLanguage, setRenderLanguage] = useState(i18n.resolvedLanguage || i18n.language);
  const activeLanguage = i18n.resolvedLanguage || i18n.language;
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
    const shared = [t('steps.language'), t('steps.mode'), t('steps.llm'), t('steps.personality')];
    return mode === 'expert'
      ? [...shared, t('steps.memory'), t('steps.tools'), t('steps.complete')]
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
        <div className="flex min-h-[420px] items-center justify-center">
          <ModeSelection
            value={mode}
            onChange={(nextMode) => {
              setMode(nextMode);
              form.setFieldValue(['preferences', 'user_mode'], nextMode);
              saveProgress(form.getFieldsValue(true));
              setCurrent(2);
            }}
          />
        </div>
      );
    }

    if (!mode) {
      return <div className="text-muted-foreground">{t('messages.chooseModeFirst')}</div>;
    }

    const quickMode = mode === 'quick';
    const language = form.getFieldValue(['preferences', 'language']) || 'zh';
    const quickSteps = [2, 3, 4];
    const expertSteps = [2, 3, 4, 5, 6];

    if (quickMode && current === quickSteps[0]) return <LLMForm quickMode />;
    if (quickMode && current === quickSteps[1]) return <PersonalityForm quickMode language={language} />;
    if (quickMode && current === quickSteps[2]) return <CompletionScreen onFinish={handleFinish} />;

    if (!quickMode && current === expertSteps[0]) return <LLMForm quickMode={false} />;
    if (!quickMode && current === expertSteps[1]) return <PersonalityForm quickMode={false} language={language} />;
    if (!quickMode && current === expertSteps[2]) return <MemoryForm />;
    if (!quickMode && current === expertSteps[3]) return <ToolsForm />;
    if (!quickMode && current === expertSteps[4]) return <CompletionScreen onFinish={handleFinish} />;

    return null;
  };

  return (
    <GuidedConfigFrame
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
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -24 }}
            transition={{ duration: 0.22, ease: 'easeOut' }}
          >
            {renderStepContent()}
          </motion.div>
        </AnimatePresence>
      </Form>
    </GuidedConfigFrame>
  );
};

export default OnboardingFlow;
