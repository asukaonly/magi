/**
 * Axios API客户端
 */
import axios, { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios';

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
const createApiClient = (): AxiosInstance => {
  const client = axios.create({
    baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api',
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

// 通用API方法
export const api = {
  get: <T = any>(url: string, params?: any) =>
    apiClient.get<ApiResponse<T>>(url, { params }).then((res) => res.data),

  post: <T = any>(url: string, data?: any) =>
    apiClient.post<ApiResponse<T>>(url, data).then((res) => res.data),

  put: <T = any>(url: string, data?: any) =>
    apiClient.put<ApiResponse<T>>(url, data).then((res) => res.data),

  delete: <T = any>(url: string) =>
    apiClient.delete<ApiResponse<T>>(url).then((res) => res.data),

  patch: <T = any>(url: string, data?: any) =>
    apiClient.patch<ApiResponse<T>>(url, data).then((res) => res.data),
};

export default apiClient;
