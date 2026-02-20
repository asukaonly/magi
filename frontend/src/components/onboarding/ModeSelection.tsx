import React from 'react';
import { motion } from 'framer-motion';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface ModeSelectionProps {
  value: 'quick' | 'expert' | null;
  onChange: (mode: 'quick' | 'expert') => void;
}

export const ModeSelection: React.FC<ModeSelectionProps> = ({ value, onChange }) => {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <motion.div whileHover={{ y: -2 }} transition={{ duration: 0.15 }}>
          <Card
            onClick={() => onChange('quick')}
            className={cn(
              'cursor-pointer transition-colors',
              value === 'quick' ? 'border-teal-600 shadow-sm' : 'hover:border-muted-foreground/40'
            )}
          >
            <CardHeader className="pb-2">
              <CardTitle className="text-base">快速模式</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              仅配置语言、LLM、人格，适合快速开始。
            </CardContent>
          </Card>
        </motion.div>
      </div>
      <div>
        <motion.div whileHover={{ y: -2 }} transition={{ duration: 0.15 }}>
          <Card
            onClick={() => onChange('expert')}
            className={cn(
              'cursor-pointer transition-colors',
              value === 'expert' ? 'border-teal-600 shadow-sm' : 'hover:border-muted-foreground/40'
            )}
          >
            <CardHeader className="pb-2">
              <CardTitle className="text-base">专家模式</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              配置完整参数（记忆层、工具管理等）。
            </CardContent>
          </Card>
        </motion.div>
      </div>
    </div>
  );
};

export default ModeSelection;
