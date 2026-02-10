/**
 * Memory页面
 */
import React, { useEffect, useState } from 'react';
import { message } from 'antd';
import { MemoryList, MemoryDetailModal } from '../components/memory';
import { useMemoryStore } from '../stores/memoryStore';
import { Memory } from '../api';

export const MemoryPage: React.FC = () => {
  const {
    memories,
    stats,
    loading,
    error,
    fetchMemories,
    searchMemories,
    deleteMemory,
    fetchStats,
    setSelectedMemory,
  } = useMemoryStore();

  const [detailModalVisible, setDetailModalVisible] = useState(false);
  const [selectedMemory, setSelectedMemoryLocal] = useState<Memory | null>(null);

  useEffect(() => {
    fetchMemories();
    fetchStats();
  }, [fetchMemories, fetchStats]);

  const handleRefresh = () => {
    fetchMemories();
    fetchStats();
  };

  const handleSearch = async (query: string) => {
    try {
      await searchMemories(query);
    } catch (error: any) {
      message.error(error.message || '搜索失败');
    }
  };

  const handleView = (memory: Memory) => {
    setSelectedMemoryLocal(memory);
    setDetailModalVisible(true);
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteMemory(id);
      message.success('记忆已删除');
      fetchStats(); // 刷新统计信息
    } catch (error: any) {
      message.error(error.message || '删除失败');
    }
  };

  return (
    <div style={{ padding: '24px' }}>
      <MemoryList
        memories={memories}
        stats={stats}
        loading={loading}
        error={error}
        onRefresh={handleRefresh}
        onSearch={handleSearch}
        onView={handleView}
        onDelete={handleDelete}
      />

      <MemoryDetailModal
        visible={detailModalVisible}
        memory={selectedMemory}
        onCancel={() => setDetailModalVisible(false)}
        onDelete={handleDelete}
      />
    </div>
  );
};
