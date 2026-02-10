/**
 * Tasks页面
 */
import React, { useEffect, useState } from 'react';
import { Modal, message } from 'antd';
import { TaskList, TaskCreateModal, TaskDetailModal } from '../components/tasks';
import { useTasksStore } from '../stores/tasksStore';
import { Task, TaskCreateRequest } from '../api';

export const TasksPage: React.FC = () => {
  const {
    tasks,
    stats,
    loading,
    error,
    fetchTasks,
    fetchStats,
    createTask,
    deleteTask,
    retryTask,
  } = useTasksStore();

  const [createModalVisible, setCreateModalVisible] = useState(false);
  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [createLoading, setCreateLoading] = useState(false);

  useEffect(() => {
    fetchTasks();
    fetchStats();
  }, [fetchTasks, fetchStats]);

  const handleRefresh = () => {
    fetchTasks();
    fetchStats();
  };

  const handleCreate = () => {
    setCreateModalVisible(true);
  };

  const handleCreateSubmit = async (data: TaskCreateRequest) => {
    setCreateLoading(true);
    try {
      await createTask(data);
      setCreateModalVisible(false);
      message.success('任务创建成功');
      fetchStats(); // 刷新统计信息
    } catch (error: any) {
      message.error(error.message || '创建失败');
      throw error;
    } finally {
      setCreateLoading(false);
    }
  };

  const handleView = (task: Task) => {
    setSelectedTask(task);
    setDetailModalVisible(true);
  };

  const handleRetry = async (id: string) => {
    Modal.confirm({
      title: '确认重试',
      content: '确定要重试这个任务吗？',
      okText: '重试',
      cancelText: '取消',
      onOk: async () => {
        try {
          await retryTask(id);
          message.success('任务重试成功');
          fetchStats(); // 刷新统计信息
        } catch (error: any) {
          message.error(error.message || '重试失败');
        }
      },
    });
  };

  const handleDelete = async (id: string) => {
    Modal.confirm({
      title: '确认删除',
      content: '确定要删除这个任务吗？此操作不可恢复。',
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await deleteTask(id);
          message.success('任务已删除');
          fetchStats(); // 刷新统计信息
        } catch (error: any) {
          message.error(error.message || '删除失败');
        }
      },
    });
  };

  return (
    <div style={{ padding: '24px' }}>
      <TaskList
        tasks={tasks}
        stats={stats}
        loading={loading}
        error={error}
        onRefresh={handleRefresh}
        onCreate={handleCreate}
        onView={handleView}
        onRetry={handleRetry}
        onDelete={handleDelete}
      />

      <TaskCreateModal
        visible={createModalVisible}
        onCancel={() => setCreateModalVisible(false)}
        onCreate={handleCreateSubmit}
        loading={createLoading}
      />

      <TaskDetailModal
        visible={detailModalVisible}
        task={selectedTask}
        onCancel={() => setDetailModalVisible(false)}
        onRetry={handleRetry}
        onDelete={handleDelete}
      />
    </div>
  );
};
