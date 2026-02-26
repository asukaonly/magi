import React from 'react';
import { cn } from '@/lib/utils';

const pathOf = (name: any): string[] => (Array.isArray(name) ? name : [name]);
const getIn = (obj: any, path: any): any => pathOf(path).reduce((acc: any, key: string) => (acc == null ? acc : acc[key]), obj);
const keyOf = (name: any): string => pathOf(name).join('.');
const setIn = (obj: any, path: any, value: any): any => {
  const next = structuredClone(obj || {});
  const parts = pathOf(path);
  let current = next;
  parts.forEach((part: string, index: number) => {
    if (index === parts.length - 1) {
      current[part] = value;
      return;
    }
    if (!current[part] || typeof current[part] !== 'object') current[part] = {};
    current = current[part];
  });
  return next;
};

const createForm = () => {
  let getStore = () => ({});
  let setStore: any = () => undefined;
  let setErrors: any = () => undefined;
  const rules = new Map<string, any[]>();
  return {
    __bind: (getter: any, setter: any, errorSetter: any) => {
      getStore = getter;
      setStore = setter;
      setErrors = errorSetter;
    },
    __registerRule: (name: any, list: any[]) => rules.set(pathOf(name).join('.'), list || []),
    getFieldValue: (name: any) => getIn(getStore(), name),
    setFieldValue: (name: any, value: any) => {
      setStore((prev: any) => setIn(prev, name, value));
      setErrors((prev: Record<string, string>) => {
        const next = { ...(prev || {}) };
        delete next[keyOf(name)];
        return next;
      });
    },
    setFieldsValue: (value: any) => setStore((prev: any) => ({ ...prev, ...value })),
    getFieldsValue: () => getStore(),
    validateFields: async () => {
      const values = getStore();
      const errorFields: Array<{ name: string; errors: string[] }> = [];
      const nextErrors: Record<string, string> = {};
      for (const [key, list] of rules.entries()) {
        const val = getIn(values, key.split('.'));
        list.forEach((rule) => {
          if (rule?.required && (val === undefined || val === null || val === '')) {
            const message = rule.message || 'required';
            errorFields.push({ name: key, errors: [message] });
            if (!nextErrors[key]) {
              nextErrors[key] = message;
            }
          }
        });
      }
      setErrors(nextErrors);
      if (errorFields.length) throw { errorFields };
      return values;
    },
  };
};

const FormContext = React.createContext<any>(null);

const FormBase = ({ form, initialValues, onValuesChange, children }: any) => {
  const [values, setValues] = React.useState(initialValues || {});
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  const instance = React.useMemo(() => form || createForm(), [form]);
  const valuesRef = React.useRef(values);
  valuesRef.current = values;

  instance.__bind(() => valuesRef.current, setValues, setErrors);

  React.useEffect(() => {
    if (initialValues) setValues(initialValues);
  }, [initialValues]);

  return <FormContext.Provider value={{ instance, values, errors, onValuesChange }}>{children}</FormContext.Provider>;
};

const FormItem = ({ label, name, valuePropName = 'value', rules, noStyle, children }: any) => {
  const ctx = React.useContext(FormContext);
  if (!ctx) return <>{children}</>;
  const { instance, values, errors, onValuesChange } = ctx;

  if (name) instance.__registerRule(name, rules);
  if (typeof children === 'function') {
    return <>{children({ getFieldValue: instance.getFieldValue, setFieldValue: instance.setFieldValue })}</>;
  }
  if (noStyle || !name) return <>{children}</>;

  const fieldKey = keyOf(name);
  const errorText = errors?.[fieldKey];
  const value = getIn(values, name);
  const normalizedValue = valuePropName === 'value' && value === null ? '' : value;
  const node = React.Children.only(children);
  return (
    <div className="space-y-2">
      {label ? <label className={cn('text-sm font-medium', errorText && 'text-destructive')}>{label}</label> : null}
      {React.cloneElement(node as React.ReactElement, {
        className: cn((node as React.ReactElement<any>).props?.className, errorText && 'border-destructive focus-visible:ring-destructive'),
        [valuePropName]: normalizedValue,
        onChange: (event: any) => {
          const next = valuePropName === 'checked'
            ? event?.target ? event.target.checked : event
            : event?.target ? event.target.value : event;
          const nextValues = setIn(values, name, next);
          instance.setFieldValue(name, next);
          onValuesChange?.({}, nextValues);
        },
      })}
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
