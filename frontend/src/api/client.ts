/**
 * Axios API客户端
 */
import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios';
import { getRuntimeConfig } from '@/runtime/config';

// API响应类型
export interface ApiResponse<T = any> {
  success: boolean;
  message: string;
  data?: T;
}

export interface ApiError {
  success: false;
  message: string;
  error_code?: string;
  details?: any;
}

export interface PaginatedResponse<T> {
  success: boolean;
  data: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// 创建axios实例
let desktopSessionToken: string | undefined;

const createApiClient = (): AxiosInstance => {
  const runtime = getRuntimeConfig();
  const client = axios.create({
    baseURL: runtime.apiBaseUrl,
    timeout: 30000,
    headers: {
      'Content-Type': 'application/json',
    },
  });

  // 请求拦截器
  client.interceptors.request.use(
    (config: InternalAxiosRequestConfig) => {
      // 添加认证token（如果有）
      const token = localStorage.getItem('auth_token');
      if (token && config.headers) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      const runtime = getRuntimeConfig();
      const sessionToken = desktopSessionToken || runtime.sessionToken;
      if (sessionToken && config.headers) {
        config.headers['X-Magi-Session-Token'] = sessionToken;
      }
      return config;
    },
    (error) => {
      return Promise.reject(error);
    }
  );

  // 响应拦截器
  client.interceptors.response.use(
    (response) => {
      return response;
    },
    (error: AxiosError<ApiError>) => {
      // 统一处理错误
      if (error.response) {
        // 服务器返回错误响应
        const errorData = error.response.data;

        // 特殊处理401未授权
        if (error.response.status === 401) {
          localStorage.removeItem('auth_token');
          window.location.href = '/login';
        }

        return Promise.reject({
          message: errorData?.message || 'An error occurred',
          code: errorData?.error_code || 'UNKNOWN_ERROR',
          status: error.response.status,
          details: errorData?.details,
        });
      } else if (error.request) {
        // 请求发送但没有收到响应
        return Promise.reject({
          message: 'No response from server',
          code: 'NETWORK_ERROR',
        });
      } else {
        // 请求配置错误
        return Promise.reject({
          message: error.message || 'Request failed',
          code: 'REQUEST_ERROR',
        });
      }
    }
  );

  return client;
};

export const apiClient = createApiClient();

export const configureApiClient = (options: {
  baseUrl?: string;
  sessionToken?: string;
} = {}): void => {
  if (options.baseUrl) {
    apiClient.defaults.baseURL = options.baseUrl.replace(/\/+$/, '');
  }
  desktopSessionToken = options.sessionToken;
  if (desktopSessionToken) {
    apiClient.defaults.headers.common['X-Magi-Session-Token'] = desktopSessionToken;
  } else {
    delete apiClient.defaults.headers.common['X-Magi-Session-Token'];
  }
};

// 通用API方法
export const api = {
  get: <T = any>(url: string, paramsOrConfig?: any) => {
    const config =
      paramsOrConfig && typeof paramsOrConfig === 'object' && 'params' in paramsOrConfig
        ? paramsOrConfig
        : paramsOrConfig
          ? { params: paramsOrConfig }
          : undefined;
    return apiClient.get<ApiResponse<T>>(url, config).then((res) => res.data);
  },

  post: <T = any>(url: string, data?: any, config?: any) =>
    apiClient.post<ApiResponse<T>>(url, data, config).then((res) => res.data),

  put: <T = any>(url: string, data?: any, config?: any) =>
    apiClient.put<ApiResponse<T>>(url, data, config).then((res) => res.data),

  delete: <T = any>(url: string, config?: any) =>
    apiClient.delete<ApiResponse<T>>(url, config).then((res) => res.data),

  patch: <T = any>(url: string, data?: any, config?: any) =>
    apiClient.patch<ApiResponse<T>>(url, data, config).then((res) => res.data),
};

export default apiClient;
