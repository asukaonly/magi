import React, { useEffect, useMemo, useState } from 'react';
import { SimpleForm as Form } from './simple-form';
import { toast } from 'sonner';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { useNavigate } from 'react-router-dom';
import { configApi } from '../../api/modules/config';
import type { SystemConfig } from '../../api/modules/config';
import LanguageForm from '../config-forms/LanguageForm';
import LLMForm from '../config-forms/LLMForm';
import PersonalityForm from '../config-forms/PersonalityForm';
import MemoryForm from '../config-forms/MemoryForm';
import ToolsForm from '../config-forms/ToolsForm';
import ModeSelection from './ModeSelection';
import StepIndicator from './StepIndicator';
import CompletionScreen from './CompletionScreen';
import { AnimatePresence, motion } from 'framer-motion';

type Mode = 'quick' | 'expert' | null;

const STORAGE_KEY = 'magi_onboarding_state';

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

  useEffect(() => {
    const configuredLanguage = initialConfig.preferences.language === 'en' ? 'en' : 'zh-CN';
    if (i18n.language !== configuredLanguage) {
      void i18n.changeLanguage(configuredLanguage);
    }
  }, [i18n, initialConfig.preferences.language]);

  const steps = useMemo(() => {
    const shared = [t('steps.language'), t('steps.mode'), t('steps.llm'), t('steps.personality')];
    return mode === 'expert'
      ? [...shared, t('steps.memory'), t('steps.tools'), t('steps.complete')]
      : [...shared, t('steps.complete')];
  }, [mode, t]);

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
        form.setFieldsValue(parsed.values);
      }
    } catch {
      // Ignore invalid cached state.
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
      const mapped = nextLanguage === 'en' ? 'en' : 'zh-CN';
      if (i18n.language !== mapped) {
        void i18n.changeLanguage(mapped);
      }
    }
    saveProgress(allValues);
  };

  const persistValues = async () => {
    const values = form.getFieldsValue(true);
    await configApi.update(values);
  };

  const handleFinish = async () => {
    const values = form.getFieldsValue(true);
    values.preferences.onboarding_completed = true;
    await configApi.update(values);
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
    try {
      setSaving(true);
      await form.validateFields();
      await persistValues();

      // Persist language preference as early as possible for UI locale switching hooks.
      if (current === 0) {
        const selectedLanguage = form.getFieldValue(['preferences', 'language']);
        if (selectedLanguage) {
          localStorage.setItem('magi_language', selectedLanguage);
          document.documentElement.lang = selectedLanguage === 'en' ? 'en' : 'zh-CN';
        }
      }

      if (isLastStep) {
        await handleFinish();
      } else {
        setCurrent((prev) => prev + 1);
      }
    } catch (error: any) {
      if (!error?.errorFields) {
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
          }}
        />
      );
    }

    if (!mode) {
      return <Card>{t('messages.chooseModeFirst')}</Card>;
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
    <Card>
      <CardContent className="space-y-4 p-4 md:p-6">
        <Form
          form={form}
          layout="vertical"
          initialValues={initialConfig}
          onValuesChange={onValuesChange}
        >
          <StepIndicator steps={steps} current={current} />
          <AnimatePresence mode="wait">
            <motion.div
              key={`${mode ?? 'none'}-${current}`}
              initial={{ opacity: 0, x: 24 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -24 }}
              transition={{ duration: 0.22, ease: 'easeOut' }}
            >
              {renderStepContent()}
            </motion.div>
          </AnimatePresence>
        </Form>

        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={handlePrev} disabled={current === 0}>
            {t('actions.previous')}
          </Button>
          <Button onClick={handleNext} disabled={saving}>
            {saving ? t('actions.saving') : isLastStep ? t('actions.finish') : t('actions.next')}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};

export default OnboardingFlow;
