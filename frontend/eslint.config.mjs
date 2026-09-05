import js from '@eslint/js';
import { defineConfig } from 'eslint/config';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default defineConfig([
  {
    ignores: [
      'dist/',
      'src/api/generated/',
      'node_modules/',
      'src-tauri/target/',
      'src-tauri/gen/',
      'src-tauri/sidecar-dist/',
      'src-tauri/Cargo.lock',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{js,mjs,cjs,ts,tsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: {
        ecmaFeatures: {
          jsx: true,
        },
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-refresh/only-export-components': 'off',
      'react-hooks/exhaustive-deps': 'off',
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': 'off',
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/ban-ts-comment': 'off',
      'no-case-declarations': 'off',
      'preserve-caught-error': 'off',
    },
  },
  {
    files: ['src/**/*.{js,ts,tsx}'],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    files: ['*.{js,mjs,cjs,ts}', 'scripts/**/*.{js,mjs,cjs,ts}', 'src/**/__tests__/**/*.{ts,tsx}', 'src/test/**/*.{ts,tsx}'],
    languageOptions: {
      globals: globals.node,
    },
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/**/__tests__/**', 'src/test/**'],
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      'react-hooks/exhaustive-deps': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unsafe-assignment': 'error',
      '@typescript-eslint/no-unsafe-member-access': 'error',
      '@typescript-eslint/no-unsafe-call': 'error',
      '@typescript-eslint/no-unsafe-argument': 'error',
      '@typescript-eslint/no-unsafe-return': 'error',
      '@typescript-eslint/ban-ts-comment': ['error', {
        'ts-ignore': true, 'ts-nocheck': true,
        'ts-expect-error': 'allow-with-description', minimumDescriptionLength: 10,
      }],
    },
  },
]);
