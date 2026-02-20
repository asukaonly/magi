import React from 'react';
import { CheckCircle2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

interface CompletionScreenProps {
  onFinish: () => void;
}

export const CompletionScreen: React.FC<CompletionScreenProps> = ({ onFinish }) => {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-4 py-10 text-center">
        <CheckCircle2 className="h-12 w-12 text-emerald-600" />
        <div>
          <h3 className="text-lg font-semibold">配置已完成</h3>
          <p className="mt-1 text-sm text-muted-foreground">你可以随时在设置页面继续修改。</p>
        </div>
        <Button onClick={onFinish}>进入应用</Button>
      </CardContent>
    </Card>
  );
};

export default CompletionScreen;
