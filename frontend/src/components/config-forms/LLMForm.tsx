import React from 'react';
import { Input } from '@/components/ui/input';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { SelectField } from './fields';

interface LLMFormProps {
  quickMode?: boolean;
}

export const LLMForm: React.FC<LLMFormProps> = ({ quickMode = false }) => {
  return (
    <>
      <Form.Item
        label="提供商"
        name={['llm', 'provider']}
        rules={[{ required: true, message: '请选择提供商' }]}
      >
        <SelectField
          options={[
            { label: 'OpenAI', value: 'openai' },
            { label: 'Anthropic', value: 'anthropic' },
            { label: 'GLM', value: 'glm' },
            { label: 'Custom', value: 'custom' },
          ]}
        />
      </Form.Item>

      <Form.Item
        label="模型名称"
        name={['llm', 'model']}
        rules={[{ required: true, message: '请输入模型名称' }]}
      >
        <Input placeholder="gpt-4o-mini" />
      </Form.Item>

      <Form.Item label="API Key" name={['llm', 'api_key']}>
        <Input type="password" placeholder="sk-..." />
      </Form.Item>

      {!quickMode && (
        <>
          <Form.Item label="Base URL" name={['llm', 'base_url']}>
            <Input placeholder="https://api.openai.com/v1" />
          </Form.Item>

          <Form.Item noStyle shouldUpdate>
            {({ getFieldValue }: { getFieldValue: (name: any) => any }) =>
              getFieldValue(['llm', 'provider']) === 'custom' ? (
                <>
                  <Form.Item
                    label="Custom Name"
                    name={['llm', 'custom_name']}
                    rules={[{ required: true, message: '请输入自定义提供商名称' }]}
                  >
                    <Input placeholder="My Provider" />
                  </Form.Item>
                  <Form.Item
                    label="API Format"
                    name={['llm', 'api_format']}
                    rules={[{ required: true, message: '请选择 API 格式' }]}
                  >
                    <SelectField
                      options={[
                        { label: 'OpenAI Compatible', value: 'openai' },
                        { label: 'Anthropic Compatible', value: 'anthropic' },
                        { label: 'Custom', value: 'custom' },
                      ]}
                    />
                  </Form.Item>
                </>
              ) : null
            }
          </Form.Item>
        </>
      )}
    </>
  );
};

export default LLMForm;
