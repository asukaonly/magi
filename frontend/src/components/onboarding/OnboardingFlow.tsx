import React, { useEffect, useMemo, useState } from 'react';
import { SimpleForm as Form } from './simple-form';
import { toast } from 'sonner';
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
  const [form] = Form.useForm();
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>(initialConfig.preferences.user_mode);
  const [current, setCurrent] = useState(0);
  const [saving, setSaving] = useState(false);

  const steps = useMemo(() => {
    const shared = ['模式选择', '语言', 'LLM', '人格'];
    return mode === 'expert' ? [...shared, '记忆', '工具', '完成'] : [...shared, '完成'];
  }, [mode]);

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
      if (isLastStep) {
        await handleFinish();
      } else {
        setCurrent((prev) => prev + 1);
      }
    } catch (error: any) {
      if (!error?.errorFields) {
        toast.error(error?.message || '保存失败');
      }
    } finally {
      setSaving(false);
    }
  };

  const handlePrev = () => setCurrent((prev) => Math.max(0, prev - 1));

  const renderStepContent = () => {
    if (current === 0) {
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
      return <Card>请先选择模式再继续。</Card>;
    }

    const quickMode = mode === 'quick';
    const language = form.getFieldValue(['preferences', 'language']) || 'zh';
    const quickSteps = [1, 2, 3, 4];
    const expertSteps = [1, 2, 3, 4, 5, 6];

    if (quickMode && current === quickSteps[0]) return <LanguageForm includeMode={false} />;
    if (quickMode && current === quickSteps[1]) return <LLMForm quickMode />;
    if (quickMode && current === quickSteps[2]) return <PersonalityForm quickMode language={language} />;
    if (quickMode && current === quickSteps[3]) return <CompletionScreen onFinish={handleFinish} />;

    if (!quickMode && current === expertSteps[0]) return <LanguageForm includeMode={false} />;
    if (!quickMode && current === expertSteps[1]) return <LLMForm quickMode={false} />;
    if (!quickMode && current === expertSteps[2]) return <PersonalityForm quickMode={false} language={language} />;
    if (!quickMode && current === expertSteps[3]) return <MemoryForm />;
    if (!quickMode && current === expertSteps[4]) return <ToolsForm />;
    if (!quickMode && current === expertSteps[5]) return <CompletionScreen onFinish={handleFinish} />;

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
            上一步
          </Button>
          <Button onClick={handleNext} disabled={saving}>
            {saving ? '保存中...' : isLastStep ? '完成' : '下一步'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};

export default OnboardingFlow;
