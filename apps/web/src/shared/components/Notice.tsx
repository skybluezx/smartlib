import { Button, InlineNotification, type InlineNotificationProps } from '@carbon/react';
import type { ReactNode } from 'react';

type NoticeProps = InlineNotificationProps & {
  actionButtonLabel?: string;
  onActionButtonClick?: () => void;
  actions?: ReactNode;
};
export function Notice({ actionButtonLabel, onActionButtonClick, actions, ...props }: NoticeProps) {
  return <div><InlineNotification {...props} />{actions ?? (actionButtonLabel && onActionButtonClick ? <Button kind="ghost" size="sm" onClick={onActionButtonClick}>{actionButtonLabel}</Button> : null)}</div>;
}
