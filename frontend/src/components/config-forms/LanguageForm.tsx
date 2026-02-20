import React from 'react';
import { useTranslation } from 'react-i18next';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { SelectField } from './fields';

interface LanguageFormProps {
  includeMode?: boolean;
}

export const LanguageForm: React.FC<LanguageFormProps> = ({ includeMode = true }) => {
  const { t } = useTranslation('onboarding');

  return (
    <>
      <Form.Item
        label={t('language.label')}
        name={['preferences', 'language']}
        rules={[{ required: true, message: t('language.required') }]}
      >
        <SelectField
          options={[
            { label: t('language.zhHans'), value: 'zh' },
            { label: t('language.en'), value: 'en' },
          ]}
        />
      </Form.Item>

      {includeMode && (
        <Form.Item label={t('mode.label')} name={['preferences', 'user_mode']}>
          <SelectField
            placeholder={t('mode.placeholder')}
            options={[
              { label: t('mode.quick'), value: 'quick' },
              { label: t('mode.expert'), value: 'expert' },
            ]}
          />
        </Form.Item>
      )}
    </>
  );
};

export default LanguageForm;
