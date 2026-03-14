import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Cloud, Globe, FileText, Wrench, ChevronDown, ChevronRight } from 'lucide-react';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { SelectField, SwitchField } from './fields';
import { Input } from '@/components/ui/input';
import { skillsApi, SkillItem } from '../../api';
import { cn } from '@/lib/utils';

interface ExpandableToolCardProps {
  icon: React.ElementType;
  label: string;
  description: string;
  checked: boolean;
  expanded: boolean;
  onToggle: (checked: boolean) => void;
  onExpand: (expanded: boolean) => void;
  children?: React.ReactNode;
}

const ExpandableToolCard: React.FC<ExpandableToolCardProps> = ({
  icon: Icon,
  label,
  description,
  checked,
  expanded,
  onToggle,
  onExpand,
  children,
}) => (
  <div
    className={cn(
      'rounded-xl border transition-all duration-200',
      checked ? 'border-primary/40 bg-primary/5' : 'border-border/60 bg-background/60'
    )}
  >
    {/* Header row with toggle */}
    <div className="flex items-center gap-3 px-4 py-3">
      <div className={cn(
        'flex h-9 w-9 items-center justify-center rounded-lg',
        checked ? 'bg-primary/10 text-primary' : 'bg-muted/50 text-muted-foreground'
      )}>
        <Icon className="h-5 w-5" />
      </div>
      <SwitchField
        checked={checked}
        onChange={onToggle}
        ariaLabel={label}
      />
      <div
        className="flex-1 cursor-pointer"
        onClick={() => checked && onExpand(!expanded)}
      >
        <div className="flex items-center justify-between">
          <div>
            <div className={cn('text-sm font-medium', checked && 'text-primary')}>
              {label}
            </div>
            <div className="text-xs leading-5 text-muted-foreground">{description}</div>
          </div>
          {checked && children && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onExpand(!expanded);
              }}
              className="rounded p-1 hover:bg-muted/50"
            >
              {expanded ? (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              )}
            </button>
          )}
        </div>
      </div>
    </div>

    {/* Expandable content */}
    {checked && expanded && children && (
      <div className="border-t border-border/40 px-4 py-3">
        <div className="space-y-4">{children}</div>
      </div>
    )}
  </div>
);

const FieldLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span className="text-xs font-medium text-muted-foreground">{children}</span>
);

export const ToolsForm: React.FC = () => {
  const { t } = useTranslation('onboarding');
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [expandedTools, setExpandedTools] = useState<Set<string>>(new Set());

  useEffect(() => {
    const loadSkills = async () => {
      try {
        const data = await skillsApi.list();
        console.log('[ToolsForm] Skills loaded:', data?.length);
        setSkills(Array.isArray(data) ? data : []);
      } catch (error) {
        console.error('[ToolsForm] Failed to load skills:', error);
        setSkills([]);
      }
    };
    void loadSkills();
  }, []);

  const toggleExpand = (tool: string) => {
    setExpandedTools((prev) => {
      const next = new Set(prev);
      if (next.has(tool)) {
        next.delete(tool);
      } else {
        next.add(tool);
      }
      return next;
    });
  };

  return (
    <Form.Item noStyle shouldUpdate>
      {({
        getFieldValue,
        setFieldValue,
      }: {
        getFieldValue: (name: any) => any;
        setFieldValue: (name: any, value: any) => void;
      }) => {
        const tools = getFieldValue(['tools']) || {};
        const builtIn = tools.builtIn || {};

        const weatherEnabled = builtIn.weather?.enabled ?? false;
        const webSearchEnabled = builtIn.webSearch?.enabled ?? false;
        const webFetchEnabled = builtIn.webFetch?.enabled ?? false;

        const patchTools = (updates: Record<string, any>) => {
          setFieldValue(['tools'], {
            ...tools,
            ...updates,
          });
        };

        const patchBuiltIn = (updates: Record<string, any>) => {
          patchTools({
            builtIn: {
              ...builtIn,
              ...updates,
            },
          });
        };

        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <h3 className="text-sm font-semibold">{t('tools.title')}</h3>
              <p className="text-xs leading-5 text-muted-foreground">{t('tools.desc')}</p>
            </div>

            <div className="space-y-3">
              {/* Weather Tool */}
              <ExpandableToolCard
                icon={Cloud}
                label={t('tools.weather.label')}
                description={t('tools.weather.desc')}
                checked={weatherEnabled}
                expanded={expandedTools.has('weather')}
                onToggle={(checked) => {
                  patchBuiltIn({
                    weather: {
                      ...builtIn.weather,
                      enabled: checked,
                    },
                  });
                  if (!checked) {
                    setExpandedTools((prev) => {
                      const next = new Set(prev);
                      next.delete('weather');
                      return next;
                    });
                  }
                }}
                onExpand={() => toggleExpand('weather')}
              >
                <div className="space-y-4">
                  <div>
                    <FieldLabel>{t('tools.weather.provider')}</FieldLabel>
                    <Form.Item name={['tools', 'builtIn', 'weather', 'provider']} noStyle>
                      <SelectField
                        options={[
                          { label: 'OpenWeather', value: 'openweather' },
                          { label: t('tools.weather.qweather'), value: 'qweather' },
                        ]}
                      />
                    </Form.Item>
                  </div>

                  <div>
                    <FieldLabel>{t('tools.weather.apiKey')}</FieldLabel>
                    <Form.Item name={['tools', 'builtIn', 'weather', 'apiKey']} noStyle>
                      <Input type="password" placeholder={t('tools.weather.apiKeyPlaceholder')} />
                    </Form.Item>
                  </div>

                  <Form.Item noStyle shouldUpdate>
                    {({ getFieldValue: getVal }: { getFieldValue: (name: any) => any }) =>
                      getVal(['tools', 'builtIn', 'weather', 'provider']) === 'qweather' ? (
                        <div>
                          <FieldLabel>{t('tools.weather.apiUrl')}</FieldLabel>
                          <Form.Item name={['tools', 'builtIn', 'weather', 'apiUrl']} noStyle>
                            <Input placeholder={t('tools.weather.apiUrlPlaceholder')} />
                          </Form.Item>
                        </div>
                      ) : null
                    }
                  </Form.Item>
                </div>
              </ExpandableToolCard>

              {/* Web Search Tool */}
              <ExpandableToolCard
                icon={Globe}
                label={t('tools.webSearch.label')}
                description={t('tools.webSearch.desc')}
                checked={webSearchEnabled}
                expanded={expandedTools.has('webSearch')}
                onToggle={(checked) => {
                  patchBuiltIn({
                    webSearch: {
                      ...builtIn.webSearch,
                      enabled: checked,
                    },
                  });
                  if (!checked) {
                    setExpandedTools((prev) => {
                      const next = new Set(prev);
                      next.delete('webSearch');
                      return next;
                    });
                  }
                }}
                onExpand={() => toggleExpand('webSearch')}
              >
                <div className="space-y-4">
                  <div>
                    <FieldLabel>{t('tools.webSearch.provider')}</FieldLabel>
                    <Form.Item name={['tools', 'builtIn', 'webSearch', 'provider']} noStyle>
                      <SelectField
                        options={[
                          { label: 'DuckDuckGo', value: 'duckduckgo' },
                          { label: 'Brave', value: 'brave' },
                          { label: 'Perplexity', value: 'perplexity' },
                          { label: 'Tavily', value: 'tavily' },
                        ]}
                      />
                    </Form.Item>
                  </div>

                  <Form.Item noStyle shouldUpdate>
                    {({ getFieldValue: getVal }: { getFieldValue: (name: any) => any }) =>
                      getVal(['tools', 'builtIn', 'webSearch', 'provider']) !== 'duckduckgo' ? (
                        <div>
                          <FieldLabel>{t('tools.webSearch.apiKey')}</FieldLabel>
                          <Form.Item name={['tools', 'builtIn', 'webSearch', 'apiKey']} noStyle>
                            <Input type="password" placeholder={t('tools.webSearch.apiKeyPlaceholder')} />
                          </Form.Item>
                        </div>
                      ) : null
                    }
                  </Form.Item>
                </div>
              </ExpandableToolCard>

              {/* Web Fetch Tool */}
              <ExpandableToolCard
                icon={FileText}
                label={t('tools.webFetch.label')}
                description={t('tools.webFetch.desc')}
                checked={webFetchEnabled}
                expanded={expandedTools.has('webFetch')}
                onToggle={(checked) => {
                  patchBuiltIn({
                    webFetch: {
                      ...builtIn.webFetch,
                      enabled: checked,
                    },
                  });
                  if (!checked) {
                    setExpandedTools((prev) => {
                      const next = new Set(prev);
                      next.delete('webFetch');
                      return next;
                    });
                  }
                }}
                onExpand={() => toggleExpand('webFetch')}
              >
                <label className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5">
                  <div className="space-y-0.5">
                    <div className="text-xs font-medium">{t('tools.webFetch.usePlaywright')}</div>
                    <div className="text-[11px] leading-4 text-muted-foreground">{t('tools.webFetch.usePlaywrightDesc')}</div>
                  </div>
                  <Form.Item name={['tools', 'builtIn', 'webFetch', 'usePlaywright']} noStyle valuePropName="checked">
                    <SwitchField />
                  </Form.Item>
                </label>
              </ExpandableToolCard>

              {/* Skills */}
              <ExpandableToolCard
                icon={Wrench}
                label={t('tools.skills.label')}
                description={skills.length > 0 ? t('tools.skills.desc', { count: skills.length }) : t('tools.skills.empty')}
                checked={tools.skills?.length > 0}
                expanded={expandedTools.has('skills')}
                onToggle={(checked) => {
                  if (skills.length === 0) return;
                  if (checked) {
                    patchTools({ skills: skills.map((s) => s.name) });
                  } else {
                    patchTools({ skills: [] });
                  }
                }}
                onExpand={() => toggleExpand('skills')}
              >
                {skills.length > 0 ? (
                  <div className="space-y-2">
                    {skills.map((skill) => (
                      <label
                        key={skill.name}
                        className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5"
                      >
                        <div className="min-w-0 flex-1 space-y-0.5">
                          <div className="text-xs font-medium">{skill.name}</div>
                          <div className="text-[11px] leading-4 text-muted-foreground">{skill.description}</div>
                        </div>
                        <div className="shrink-0">
                          <SwitchField
                            checked={tools.skills?.includes(skill.name) ?? false}
                            onChange={(checked) => {
                              const currentSkills = tools.skills || [];
                              if (checked) {
                                patchTools({ skills: [...currentSkills, skill.name] });
                              } else {
                                patchTools({ skills: currentSkills.filter((s: string) => s !== skill.name) });
                              }
                            }}
                            ariaLabel={skill.name}
                          />
                        </div>
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-muted-foreground">{t('tools.skills.emptyHint')}</div>
                )}
              </ExpandableToolCard>
            </div>
          </div>
        );
      }}
    </Form.Item>
  );
};

export default ToolsForm;
