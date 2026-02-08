/**
 * Metrics状态管理
 */
import { create } from 'zustand';
import { metricsApi, SystemMetrics, AgentMetrics } from '../api';

interface MetricsState {
  systemMetrics: SystemMetrics | null;
  agentMetrics: AgentMetrics[];
  healthStatus: any;
  loading: boolean;
  error: string | null;

  // Actions
  fetchSystemMetrics: () => Promise<void>;
  fetchAgentMetrics: () => Promise<void>;
  fetchHealthStatus: () => Promise<void>;
}

export const useMetricsStore = create<MetricsState>((set) => ({
  systemMetrics: null,
  agentMetrics: [],
  healthStatus: null,
  loading: false,
  error: null,

  fetchSystemMetrics: async () => {
    set({ loading: true, error: null });
    try {
      const response = await metricsApi.getSystem();
      set({ systemMetrics: response.data, loading: false });
    } catch (error: any) {
      set({ error: error.message || 'Failed to fetch system metrics', loading: false });
    }
  },

  fetchAgentMetrics: async () => {
    set({ loading: true, error: null });
    try {
      const response = await metricsApi.getAgents();
      set({ agentMetrics: response.data || [], loading: false });
    } catch (error: any) {
      set({ error: error.message || 'Failed to fetch agent metrics', loading: false });
    }
  },

  fetchHealthStatus: async () => {
    try {
      const response = await metricsApi.getHealth();
      set({ healthStatus: response.data });
    } catch (error: any) {
      console.error('Failed to fetch health status:', error);
    }
  },
}));
