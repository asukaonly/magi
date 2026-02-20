import React, { useEffect, useMemo, useState } from 'react';
import { Input } from '@/components/ui/input';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { CheckboxGroupField, SelectField, SwitchField } from './fields';
import { skillsApi, SkillItem } from '../../api';

export const ToolsForm: React.FC = () => {
  const [skills, setSkills] = useState<SkillItem[]>([]);

  useEffect(() => {
    const loadSkills = async () => {
      try {
        const response = await skillsApi.list();
        setSkills(response.data || []);
      } catch (error) {
        setSkills([]);
      }
    };
    void loadSkills();
  }, []);

  const skillOptions = useMemo(
    () =>
      skills.map((item) => ({
        label: `${item.name} - ${item.description}`,
        value: item.name,
      })),
    [skills]
  );

  return (
    <>
      <Form.Item label="天气工具启用" name={['tools', 'builtIn', 'weather', 'enabled']} valuePropName="checked">
        <SwitchField />
      </Form.Item>
      <Form.Item label="天气服务商" name={['tools', 'builtIn', 'weather', 'provider']}>
        <SelectField
          options={[
            { label: 'OpenWeather', value: 'openweather' },
            { label: '和风天气', value: 'qweather' },
          ]}
        />
      </Form.Item>
      <Form.Item label="天气 API Key" name={['tools', 'builtIn', 'weather', 'apiKey']}>
        <Input type="password" />
      </Form.Item>
      <Form.Item noStyle shouldUpdate>
        {({ getFieldValue }: { getFieldValue: (name: any) => any }) =>
          getFieldValue(['tools', 'builtIn', 'weather', 'provider']) === 'qweather' ? (
            <Form.Item label="天气 API URL" name={['tools', 'builtIn', 'weather', 'apiUrl']}>
              <Input />
            </Form.Item>
          ) : null
        }
      </Form.Item>

      <Form.Item label="网页搜索启用" name={['tools', 'builtIn', 'webSearch', 'enabled']} valuePropName="checked">
        <SwitchField />
      </Form.Item>
      <Form.Item label="网页搜索服务商" name={['tools', 'builtIn', 'webSearch', 'provider']}>
        <SelectField
          options={[
            { label: 'DuckDuckGo', value: 'duckduckgo' },
            { label: 'Brave', value: 'brave' },
            { label: 'Perplexity', value: 'perplexity' },
            { label: 'Tavily', value: 'tavily' },
            { label: 'Google', value: 'google' },
          ]}
        />
      </Form.Item>
      <Form.Item noStyle shouldUpdate>
        {({ getFieldValue }: { getFieldValue: (name: any) => any }) =>
          getFieldValue(['tools', 'builtIn', 'webSearch', 'provider']) !== 'duckduckgo' ? (
            <Form.Item label="网页搜索 API Key" name={['tools', 'builtIn', 'webSearch', 'apiKey']}>
              <Input type="password" />
            </Form.Item>
          ) : null
        }
      </Form.Item>

      <Form.Item label="网页获取启用" name={['tools', 'builtIn', 'webFetch', 'enabled']} valuePropName="checked">
        <SwitchField />
      </Form.Item>
      <Form.Item label="使用 Playwright 渲染" name={['tools', 'builtIn', 'webFetch', 'usePlaywright']} valuePropName="checked">
        <SwitchField />
      </Form.Item>

      <Form.Item label="启用 Skills" name={['tools', 'skills']}>
        <CheckboxGroupField options={skillOptions} />
      </Form.Item>
    </>
  );
};

export default ToolsForm;
