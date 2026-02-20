import React, { useEffect, useState } from 'react';
import { Textarea } from '@/components/ui/textarea';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { SelectField } from './fields';
import { personalitiesApi, PersonalityPreset } from '../../api';

interface PersonalityFormProps {
  quickMode?: boolean;
  language?: 'zh' | 'en';
}

export const PersonalityForm: React.FC<PersonalityFormProps> = ({ quickMode = false, language = 'zh' }) => {
  const [presets, setPresets] = useState<PersonalityPreset[]>([]);

  useEffect(() => {
    const loadPresets = async () => {
      try {
        const response = await personalitiesApi.list(language);
        setPresets(response.data || []);
      } catch (error) {
        setPresets([]);
      }
    };
    void loadPresets();
  }, [language]);

  return (
    <>
      <Form.Item label="预设人格" name={['personality', 'preset']}>
        <SelectField
          placeholder="选择预设人格"
          options={presets.map((item) => ({
            label: `${item.name} - ${item.description}`,
            value: item.id,
          }))}
        />
      </Form.Item>

      {!quickMode && (
        <>
          <Form.Item label="自定义提示词" name={['personality', 'custom_prompt']}>
            <Textarea rows={5} placeholder="请输入自定义人格提示词" />
          </Form.Item>
          <Form.Item label="语调" name={['personality', 'tone']}>
            <SelectField
              options={[
                { label: '随意', value: 'casual' },
                { label: '正式', value: 'formal' },
              ]}
            />
          </Form.Item>
        </>
      )}
    </>
  );
};

export default PersonalityForm;
