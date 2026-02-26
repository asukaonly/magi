import React from 'react';
import { useForm as useReactHookForm, type UseFormReturn } from 'react-hook-form';
import { z } from 'zod';
import { cn } from '@/lib/utils';

type NamePath = string | number | Array<string | number>;
type Rule = { required?: boolean; message?: string };
type RulesStore = Map<string, Rule[]>;

const pathOf = (name: NamePath): Array<string | number> => (Array.isArray(name) ? name : [name]);
const keyOf = (name: NamePath): string => pathOf(name).join('.');

const getIn = (obj: any, path: NamePath): any =>
  pathOf(path).reduce((acc: any, key: string | number) => (acc == null ? acc : acc[key]), obj);

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const mergeDeep = (base: Record<string, any>, patch: Record<string, any>): Record<string, any> => {
  const next: Record<string, any> = { ...base };
  Object.entries(patch).forEach(([key, value]) => {
    if (isPlainObject(value) && isPlainObject(base[key])) {
      next[key] = mergeDeep(base[key] as Record<string, any>, value);
      return;
    }
    next[key] = value;
  });
  return next;
};

const isEmptyValue = (value: unknown): boolean =>
  value === undefined ||
  value === null ||
  value === '' ||
  (Array.isArray(value) && value.length === 0);

const flattenFieldErrors = (error: unknown, parent = ''): Record<string, string> => {
  if (!isPlainObject(error)) {
    return {};
  }
  const entries = Object.entries(error);
  return entries.reduce((acc, [key, value]) => {
    const nextKey = parent ? `${parent}.${key}` : key;
    if (isPlainObject(value) && 'message' in value && typeof value.message === 'string') {
      acc[nextKey] = value.message;
      return acc;
    }
    Object.assign(acc, flattenFieldErrors(value, nextKey));
    return acc;
  }, {} as Record<string, string>);
};

const createSchemaFromRules = (rules: RulesStore): z.ZodTypeAny =>
  z
    .object({})
    .passthrough()
    .superRefine((values, ctx) => {
      for (const [key, list] of rules.entries()) {
        const requiredRule = list?.find((rule) => rule?.required);
        if (!requiredRule) continue;
        const value = getIn(values, key.split('.'));
        if (isEmptyValue(value)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: key.split('.'),
            message: requiredRule.message || 'required',
          });
        }
      }
    });

const createForm = () => {
  let methods: UseFormReturn<any> | null = null;
  let onValuesChange: any = undefined;
  const rules: RulesStore = new Map();

  return {
    __bind: (nextMethods: UseFormReturn<any>, valuesChangeCallback?: any) => {
      methods = nextMethods;
      onValuesChange = valuesChangeCallback;
    },
    __registerRule: (name: NamePath, list: Rule[]) => {
      rules.set(keyOf(name), list || []);
    },
    getFieldValue: (name: NamePath) => methods?.getValues(keyOf(name) as any),
    setFieldValue: (name: NamePath, value: any) => {
      if (!methods) return;
      methods.setValue(keyOf(name) as any, value, {
        shouldTouch: true,
        shouldDirty: true,
        shouldValidate: false,
      });
      methods.clearErrors(keyOf(name) as any);
      onValuesChange?.({}, methods.getValues());
    },
    setFieldsValue: (value: Record<string, any>) => {
      if (!methods) return;
      const merged = mergeDeep(methods.getValues() || {}, value || {});
      methods.reset(merged, { keepErrors: true });
    },
    getFieldsValue: () => methods?.getValues() || {},
    validateFields: async () => {
      if (!methods) return {};
      const values = methods.getValues();
      const parsed = createSchemaFromRules(rules).safeParse(values);
      methods.clearErrors();
      if (!parsed.success) {
        const errorFields: Array<{ name: string; errors: string[] }> = [];
        parsed.error.issues.forEach((issue) => {
          const path = issue.path.join('.');
          errorFields.push({ name: path, errors: [issue.message] });
          methods?.setError(path as any, { type: 'manual', message: issue.message });
        });
        throw { errorFields };
      }
      return parsed.data;
    },
  };
};

const FormContext = React.createContext<{
  instance: any;
  values: any;
  errors: Record<string, string>;
  onValuesChange?: any;
} | null>(null);

const FormBase = ({ form, initialValues, onValuesChange, children }: any) => {
  const instance = React.useMemo(() => form || createForm(), [form]);
  const methods = useReactHookForm({
    defaultValues: initialValues || {},
    mode: 'onSubmit',
  });
  const values = methods.watch();
  const errors = React.useMemo(() => flattenFieldErrors(methods.formState.errors), [methods.formState.errors]);

  React.useEffect(() => {
    instance.__bind(methods, onValuesChange);
  }, [instance, methods, onValuesChange]);

  React.useEffect(() => {
    if (initialValues) {
      methods.reset(initialValues);
    }
  }, [initialValues, methods]);

  return <FormContext.Provider value={{ instance, values, errors, onValuesChange }}>{children}</FormContext.Provider>;
};

const FormItem = ({ label, name, valuePropName = 'value', rules, noStyle, children }: any) => {
  const ctx = React.useContext(FormContext);
  if (!ctx) return <>{children}</>;
  const { instance, values, errors } = ctx;

  React.useEffect(() => {
    if (name) {
      instance.__registerRule(name, rules);
    }
  }, [instance, name, rules]);

  if (typeof children === 'function') {
    return <>{children({ getFieldValue: instance.getFieldValue, setFieldValue: instance.setFieldValue })}</>;
  }

  const fieldKey = name ? keyOf(name) : null;
  const errorText = fieldKey ? errors?.[fieldKey] : undefined;
  const value = name ? getIn(values, name) : undefined;
  const normalizedValue = valuePropName === 'value' && value === null ? '' : value;

  const injectValueBinding = (node: React.ReactElement): React.ReactElement =>
    React.cloneElement(node, {
      className: cn(node.props?.className, errorText && 'border-destructive focus-visible:ring-destructive'),
      [valuePropName]: normalizedValue,
      onChange: (event: any) => {
        const next =
          valuePropName === 'checked'
            ? event?.target
              ? event.target.checked
              : event
            : event?.target
              ? event.target.value
              : event;
        instance.setFieldValue(name, next);
        node.props?.onChange?.(event);
      },
    });

  const processChildren = (childrenNode: React.ReactNode): React.ReactNode => {
    if (!name) return childrenNode;

    if (React.isValidElement(childrenNode)) {
      const childType = (childrenNode as React.ReactElement).type;

      if (typeof childType === 'function' || typeof childType === 'object') {
        const typeName = (childType as any)?.displayName || (childType as any)?.name || '';
        if (typeName === 'Input' || typeName === 'Select' || typeName === 'Textarea' || typeName.endsWith('Field')) {
          return injectValueBinding(childrenNode as React.ReactElement);
        }
      }

      if (childType === 'input' || childType === 'textarea' || childType === 'select') {
        return injectValueBinding(childrenNode as React.ReactElement);
      }

      const props = (childrenNode as React.ReactElement).props;
      if (props?.children) {
        return React.cloneElement(childrenNode as React.ReactElement, {
          children: processChildren(props.children),
        });
      }
    }

    if (Array.isArray(childrenNode)) {
      let found = false;
      return React.Children.map(childrenNode, (child) => {
        if (found || !React.isValidElement(child)) return child;
        const result = processChildren(child);
        if (result !== child) found = true;
        return result;
      });
    }

    return childrenNode;
  };

  if (!name) {
    if (noStyle || !label) return <>{children}</>;
    return (
      <div className="space-y-2">
        {label ? <label className={cn('text-sm font-medium')}>{label}</label> : null}
        {children}
      </div>
    );
  }

  const processedChildren = processChildren(children);

  if (noStyle) {
    return <>{processedChildren}</>;
  }

  return (
    <div className="space-y-2">
      {label ? <label className={cn('text-sm font-medium', errorText && 'text-destructive')}>{label}</label> : null}
      {processedChildren}
      {errorText ? <p className="text-xs text-destructive">{errorText}</p> : null}
    </div>
  );
};

const useForm = () => {
  const formRef = React.useRef<any>();
  if (!formRef.current) {
    formRef.current = createForm();
  }
  return [formRef.current];
};

export const SimpleForm: any = Object.assign(FormBase, { Item: FormItem, useForm });
export { FormContext };
