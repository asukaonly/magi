/**
 * Tools页面
 */
import React, { useEffect, useState } from 'react';
import { message } from 'antd';
import { ToolList, ToolDetailModal, ToolTestModal } from '../components/tools';
import { useToolsStore } from '../stores/toolsStore';
import { Tool } from '../api';

export const ToolsPage: React.FC = () => {
  const {
    tools,
    categories,
    loading,
    error,
    fetchTools,
    fetchCategories,
    testTool,
  } = useToolsStore();

  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [testModalVisible, setTestModalVisible] = useState(false);
  const [selectedTool, setSelectedTool] = useState<Tool | null>(null);
  const [testLoading, setTestLoading] = useState(false);

  useEffect(() => {
    fetchTools();
    fetchCategories();
  }, [fetchTools, fetchCategories]);

  const handleRefresh = () => {
    fetchTools();
    fetchCategories();
  };

  const handleView = (tool: Tool) => {
    setSelectedTool(tool);
    setDetailModalVisible(true);
  };

  const handleTest = (tool: Tool) => {
    setSelectedTool(tool);
    setTestModalVisible(true);
  };

  const handleExecuteTest = async (name: string, params: Record<string, any>) => {
    setTestLoading(true);
    try {
      const result = await testTool(name, params);
      message.success('工具测试成功');
      return result;
    } catch (error: any) {
      message.error(error.message || '测试失败');
      throw error;
    } finally {
      setTestLoading(false);
    }
  };

  return (
    <div style={{ padding: '24px' }}>
      <ToolList
        tools={tools}
        categories={categories}
        loading={loading}
        error={error}
        onRefresh={handleRefresh}
        onView={handleView}
        onTest={handleTest}
      />

      <ToolDetailModal
        visible={detailModalVisible}
        tool={selectedTool}
        onCancel={() => setDetailModalVisible(false)}
        onTest={handleTest}
      />

      <ToolTestModal
        visible={testModalVisible}
        tool={selectedTool}
        onCancel={() => setTestModalVisible(false)}
        onTest={handleExecuteTest}
        loading={testLoading}
      />
    </div>
  );
};
