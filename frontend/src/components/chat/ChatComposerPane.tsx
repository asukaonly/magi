import { ChatComposerShell, type ChatComposerShellProps } from './ChatComposerShell';
import { ComposerAttachmentInputs, type ComposerAttachmentInputsProps } from './ComposerAttachmentInputs';

const IMAGE_ATTACHMENT_ACCEPT = 'image/png,image/jpeg,image/webp';
const FILE_ATTACHMENT_ACCEPT = '.txt,.md,.json,.pdf,.ts,.tsx,.js,.jsx,.py,.rs,.go,.java,.kt,.swift,.c,.cc,.cpp,.h,.hpp,.html,.css,.csv,.xml,.yaml,.yml,.toml,.ini,.log,.sh,.sql,.php,.rb';

type ChatComposerPaneProps = ChatComposerShellProps & {
  imageInputRef: ComposerAttachmentInputsProps['imageInputRef'];
  fileInputRef: ComposerAttachmentInputsProps['fileInputRef'];
  onAttachmentInputChange: ComposerAttachmentInputsProps['onChange'];
};

export const ChatComposerPane = ({
  imageInputRef,
  fileInputRef,
  onAttachmentInputChange,
  ...composerShellProps
}: ChatComposerPaneProps) => {
  return (
    <div className="mx-auto w-full max-w-[1080px] shrink-0">
      <ChatComposerShell {...composerShellProps} />
      <ComposerAttachmentInputs
        imageInputRef={imageInputRef}
        fileInputRef={fileInputRef}
        imageAccept={IMAGE_ATTACHMENT_ACCEPT}
        fileAccept={FILE_ATTACHMENT_ACCEPT}
        onChange={onAttachmentInputChange}
      />
    </div>
  );
};
