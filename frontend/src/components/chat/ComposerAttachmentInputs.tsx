import type { ChangeEventHandler, Ref } from 'react';

export type ComposerAttachmentInputsProps = {
  imageInputRef: Ref<HTMLInputElement>;
  fileInputRef: Ref<HTMLInputElement>;
  imageAccept: string;
  fileAccept: string;
  onChange: ChangeEventHandler<HTMLInputElement>;
};

export const ComposerAttachmentInputs = ({
  imageInputRef,
  fileInputRef,
  imageAccept,
  fileAccept,
  onChange,
}: ComposerAttachmentInputsProps) => {
  return (
    <>
      <input
        ref={imageInputRef}
        data-testid="chat-attachments-image-input"
        type="file"
        accept={imageAccept}
        multiple
        className="hidden"
        onChange={onChange}
      />
      <input
        ref={fileInputRef}
        data-testid="chat-attachments-file-input"
        type="file"
        accept={fileAccept}
        multiple
        className="hidden"
        onChange={onChange}
      />
    </>
  );
};