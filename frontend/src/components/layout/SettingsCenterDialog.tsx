import React from 'react';
import { Dialog, DialogContent } from '@/components/ui/dialog';
import { SettingsPage } from '@/pages/Settings';

interface SettingsCenterDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const SettingsCenterDialog: React.FC<SettingsCenterDialogProps> = ({ open, onOpenChange }) => {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="h-[88vh] max-w-6xl overflow-hidden p-0">
        <SettingsPage />
      </DialogContent>
    </Dialog>
  );
};

export default SettingsCenterDialog;

