import React from 'react';

const pathOf = (name: any): string[] => (Array.isArray(name) ? name : [name]);
const getIn = (obj: any, path: any): any => pathOf(path).reduce((acc: any, key: string) => (acc == null ? acc : acc[key]), obj);
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
  const rules = new Map<string, any[]>();
  return {
    __bind: (getter: any, setter: any) => {
      getStore = getter;
      setStore = setter;
    },
    __registerRule: (name: any, list: any[]) => rules.set(pathOf(name).join('.'), list || []),
    getFieldValue: (name: any) => getIn(getStore(), name),
    setFieldValue: (name: any, value: any) => setStore((prev: any) => setIn(prev, name, value)),
    setFieldsValue: (value: any) => setStore((prev: any) => ({ ...prev, ...value })),
    getFieldsValue: () => getStore(),
    validateFields: async () => {
      const values = getStore();
      const errorFields: Array<{ name: string; errors: string[] }> = [];
      for (const [key, list] of rules.entries()) {
        const val = getIn(values, key.split('.'));
        list.forEach((rule) => {
          if (rule?.required && (val === undefined || val === null || val === '')) {
            errorFields.push({ name: key, errors: [rule.message || 'required'] });
          }
        });
      }
      if (errorFields.length) throw { errorFields };
      return values;
    },
  };
};

const FormContext = React.createContext<any>(null);

const FormBase = ({ form, initialValues, onValuesChange, children }: any) => {
  const [values, setValues] = React.useState(initialValues || {});
  const instance = React.useMemo(() => form || createForm(), [form]);
  const valuesRef = React.useRef(values);
  valuesRef.current = values;

  instance.__bind(() => valuesRef.current, setValues);

  React.useEffect(() => {
    if (initialValues) setValues(initialValues);
  }, [initialValues]);

  return <FormContext.Provider value={{ instance, values, onValuesChange }}>{children}</FormContext.Provider>;
};

const FormItem = ({ label, name, valuePropName = 'value', rules, noStyle, children }: any) => {
  const ctx = React.useContext(FormContext);
  if (!ctx) return <>{children}</>;
  const { instance, values, onValuesChange } = ctx;

  if (name) instance.__registerRule(name, rules);
  if (typeof children === 'function') {
    return <>{children({ getFieldValue: instance.getFieldValue, setFieldValue: instance.setFieldValue })}</>;
  }
  if (noStyle || !name) return <>{children}</>;

  const value = getIn(values, name);
  const node = React.Children.only(children);
  return (
    <div className="space-y-2">
      {label ? <label className="text-sm font-medium">{label}</label> : null}
      {React.cloneElement(node as React.ReactElement, {
        [valuePropName]: value,
        onChange: (event: any) => {
          const next = valuePropName === 'checked'
            ? event?.target ? event.target.checked : event
            : event?.target ? event.target.value : event;
          const nextValues = setIn(values, name, next);
          instance.setFieldValue(name, next);
          onValuesChange?.({}, nextValues);
        },
      })}
    </div>
  );
};

export const SimpleForm: any = Object.assign(FormBase, { Item: FormItem, useForm: () => [createForm()] });
