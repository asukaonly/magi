import React from 'react';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { CheckboxGroupField, SelectField, SwitchField } from './fields';

export const MemoryForm: React.FC = () => {
  return (
    <>
      <Form.Item label="L1 原始事件" name={['memory_layers', 'L1', 'enabled']} valuePropName="checked">
        <SwitchField />
      </Form.Item>

      <Form.Item noStyle shouldUpdate>
        {({
          getFieldValue,
          setFieldValue,
        }: {
          getFieldValue: (name: any) => any;
          setFieldValue: (name: any, value: any) => void;
        }) => {
          const l1Enabled = getFieldValue(['memory_layers', 'L1', 'enabled']) !== false;
          const forceEnableL1 = () => setFieldValue(['memory_layers', 'L1', 'enabled'], true);

          return (
            <>
              {!l1Enabled && (
                <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm">
                  <div className="font-medium text-amber-800">L2-L5 依赖 L1</div>
                  <div className="mt-1 text-amber-700">当前 L1 已关闭，其他层将被禁用。</div>
                  <Button variant="outline" size="sm" className="mt-2" onClick={forceEnableL1}>
                    一键启用 L1
                  </Button>
                </div>
              )}

              <Form.Item label="L2 关系层开关" name={['memory_layers', 'L2', 'enabled']} valuePropName="checked">
                <SwitchField disabled={!l1Enabled} />
              </Form.Item>
              <Form.Item label="L2 Backend" name={['memory_layers', 'L2', 'backend']}>
                <SelectField
                  disabled={!l1Enabled}
                  options={[
                    { label: 'SQLite + NetworkX', value: 'sqlite_networkx' },
                    { label: 'Kuzu', value: 'kuzu' },
                  ]}
                />
              </Form.Item>
              <Form.Item label="L2 图关系规则" name={['memory_layers', 'L2', 'graphRules']}>
                <Textarea
                  disabled={!l1Enabled}
                  rows={3}
                  placeholder="输入图关系生成规则"
                />
              </Form.Item>

              <Form.Item label="L3 语义层开关" name={['memory_layers', 'L3', 'enabled']} valuePropName="checked">
                <SwitchField disabled={!l1Enabled} />
              </Form.Item>
              <Form.Item label="L3 部署方式" name={['memory_layers', 'L3', 'deployment']}>
                <SelectField
                  disabled={!l1Enabled}
                  options={[
                    { label: '本地', value: 'local' },
                    { label: '远程', value: 'remote' },
                  ]}
                />
              </Form.Item>
              <Form.Item label="L3 模型" name={['memory_layers', 'L3', 'model']}>
                <SelectField
                  disabled={!l1Enabled}
                  options={[
                    { label: 'nomic-embed-text', value: 'nomic-embed-text' },
                    { label: 'bge-m3', value: 'bge-m3' },
                    { label: 'text-embedding-3-large', value: 'text-embedding-3-large' },
                  ]}
                />
              </Form.Item>

              <Form.Item label="L4 摘要层开关" name={['memory_layers', 'L4', 'enabled']} valuePropName="checked">
                <SwitchField disabled={!l1Enabled} />
              </Form.Item>
              <Form.Item label="L4 摘要类型" name={['memory_layers', 'L4', 'summaryTypes']}>
                <CheckboxGroupField
                  disabled={!l1Enabled}
                  options={[
                    { label: '用户事件摘要', value: 'user_events' },
                    { label: 'AI 工具执行摘要', value: 'ai_tool_execution' },
                    { label: '外部感知摘要', value: 'external_perception' },
                  ]}
                />
              </Form.Item>

              <Form.Item label="L5 能力层开关" name={['memory_layers', 'L5', 'enabled']} valuePropName="checked">
                <SwitchField disabled={!l1Enabled} />
              </Form.Item>
            </>
          );
        }}
      </Form.Item>
    </>
  );
};

export default MemoryForm;
