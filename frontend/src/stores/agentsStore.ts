/**
 * Agents状态管理
 */
import { create } from 'zustand';
import { Agent, agentsApi } from '../api';

interface AgentsState {
  agents: Agent[];
  selectedAgent: Agent | null;
  loading: boolean;
  error: string | null;

  // Actions
  fetchAgents: () => Promise<void>;
  fetchAgent: (id: string) => Promise<void>;
  createAgent: (data: any) => Promise<void>;
  updateAgent: (id: string, data: any) => Promise<void>;
  deleteAgent: (id: string) => Promise<void>;
  agentAction: (id: string, action: string) => Promise<void>;
  setSelectedAgent: (agent: Agent | null) => void;
}

export const useAgentsStore = create<AgentsState>((set, get) => ({
  agents: [],
  selectedAgent: null,
  loading: false,
  error: null,

  fetchAgents: async () => {
    set({ loading: true, error: null });
    try {
      const response = await agentsApi.list();
      set({ agents: response.data || [], loading: false });
    } catch (error: any) {
      set({ error: error.message || 'Failed to fetch agents', loading: false });
    }
  },

  fetchAgent: async (id: string) => {
    set({ loading: true, error: null });
    try {
      const response = await agentsApi.get(id);
      set({ selectedAgent: response.data, loading: false });
    } catch (error: any) {
      set({ error: error.message || 'Failed to fetch agent', loading: false });
    }
  },

  createAgent: async (data) => {
    set({ loading: true, error: null });
    try {
      const response = await agentsApi.create(data);
      const newAgent = response.data;
      set((state) => ({
        agents: [...state.agents, newAgent],
        loading: false,
      }));
      return newAgent;
    } catch (error: any) {
      set({ error: error.message || 'Failed to create agent', loading: false });
      throw error;
    }
  },

  updateAgent: async (id, data) => {
    set({ loading: true, error: null });
    try {
      const response = await agentsApi.update(id, data);
      const updatedAgent = response.data;
      set((state) => ({
        agents: state.agents.map((a) => (a.id === id ? updatedAgent : a)),
        selectedAgent: state.selectedAgent?.id === id ? updatedAgent : state.selectedAgent,
        loading: false,
      }));
    } catch (error: any) {
      set({ error: error.message || 'Failed to update agent', loading: false });
      throw error;
    }
  },

  deleteAgent: async (id) => {
    set({ loading: true, error: null });
    try {
      await agentsApi.delete(id);
      set((state) => ({
        agents: state.agents.filter((a) => a.id !== id),
        selectedAgent: state.selectedAgent?.id === id ? null : state.selectedAgent,
        loading: false,
      }));
    } catch (error: any) {
      set({ error: error.message || 'Failed to delete agent', loading: false });
      throw error;
    }
  },

  agentAction: async (id, action) => {
    set({ loading: true, error: null });
    try {
      const response = await agentsApi.action(id, { action });
      const updatedAgent = response.data.data;
      set((state) => ({
        agents: state.agents.map((a) => (a.id === id ? updatedAgent : a)),
        selectedAgent: state.selectedAgent?.id === id ? updatedAgent : state.selectedAgent,
        loading: false,
      }));
    } catch (error: any) {
      set({ error: error.message || 'Failed to perform action', loading: false });
      throw error;
    }
  },

  setSelectedAgent: (agent) => {
    set({ selectedAgent: agent });
  },
}));
