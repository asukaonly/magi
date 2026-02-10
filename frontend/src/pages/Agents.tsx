/**
 * Agents页面
 */
import React, { useEffect, useState } from 'react';
import { Modal, message } from 'antd';
import { AgentList, AgentCreateModal, AgentDetailModal } from '../components/agents';
import { useAgentsStore } from '../stores/agentsStore';
import { Agent, AgentCreateRequest } from '../api';

export const AgentsPage: React.FC = () => {
  const {
    agents,
    loading,
    error,
    fetchAgents,
    createAgent,
    deleteAgent,
    agentAction,
  } = useAgentsStore();

  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [createLoading, setCreateLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  useEffect(() => {
    fetchAgents();
  }, [fetchAgents]);

  const handleRefresh = () => {
    fetchAgents();
  };

  const handleCreate = () => {
    setCreateModalVisible(true);
  };

  const handleCreateSubmit = async (data: AgentCreateRequest) => {
    setCreateLoading(true);
    try {
      await createAgent(data);
      setCreateModalVisible(false);
      message.success('Agent创建成功');
    } catch (error: any) {
      message.error(error.message || '创建失败');
      throw error;
    } finally {
      setCreateLoading(false);
    }
  };

  const handleView = (agent: Agent) => {
    setSelectedAgent(agent);
    setDetailModalVisible(true);
  };

  const handleEdit = (agent: Agent) => {
    message.info('编辑功能即将开放');
    // TODO: 实现编辑功能
  };

  const handleDelete = async (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个Agent吗？此操作不可恢复。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteAgent(id);
          message.success('Agent已删除');
        } catch (error: any) {
          message.error(error.message || '删除失败');
        }
      },
    });
  };

  const handleStart = async (id: string) => {
    setActionLoading(true);
    try {
      await agentAction(id, 'start');
      message.success('Agent启动成功');
    } catch (error: any) {
      message.error(error.message || '启动失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handleStop = async (id: string) => {
    setActionLoading(true);
    try {
      await agentAction(id, 'stop');
      message.success('Agent已停止');
    } catch (error: any) {
      message.error(error.message || '停止失败');
    } finally {
      setActionLoading(false);
    }
  };

  const handleRestart = async (id: string) => {
    setActionLoading(true);
    try {
      await agentAction(id, 'restart');
      message.success('Agent重启成功');
    } catch (error: any) {
      message.error(error.message || '重启失败');
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div style={{ padding: '24px' }}>
      <AgentList
        agents={agents}
        loading={loading}
        error={error}
        onRefresh={handleRefresh}
        onCreate={handleCreate}
        onView={handleView}
        onEdit={handleEdit}
        onDelete={handleDelete}
        onStart={handleStart}
        onStop={handleStop}
        onRestart={handleRestart}
      />

      <AgentCreateModal
        visible={createModalVisible}
        onCancel={() => setCreateModalVisible(false)}
        onCreate={handleCreateSubmit}
        loading={createLoading}
      />

      <AgentDetailModal
        visible={detailModalVisible}
        agent={selectedAgent}
        onCancel={() => setDetailModalVisible(false)}
        onStart={handleStart}
        onStop={handleStop}
        onRestart={handleRestart}
      />
    </div>
  );
};
