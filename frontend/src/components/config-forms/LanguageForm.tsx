import React from 'react';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { SelectField } from './fields';

interface LanguageFormProps {
  includeMode?: boolean;
}

export const LanguageForm: React.FC<LanguageFormProps> = ({ includeMode = true }) => {
  return (
    <>
      <Form.Item
        label="界面语言"
        name={['preferences', 'language']}
        rules={[{ required: true, message: '请选择语言' }]}
      >
        <SelectField
          options={[
            { label: '中文（简体）', value: 'zh' },
            { label: 'English', value: 'en' },
          ]}
        />
      </Form.Item>

      {includeMode && (
        <Form.Item label="用户模式" name={['preferences', 'user_mode']}>
          <SelectField
            placeholder="请选择模式"
            options={[
              { label: '快速模式', value: 'quick' },
              { label: '专家模式', value: 'expert' },
            ]}
          />
        </Form.Item>
      )}
    </>
  );
};

export default LanguageForm;
