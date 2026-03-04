import type { NotificationEntityType, NotificationInput } from "../app/state/notificationsStore";

type PushFn = (input: NotificationInput) => string;

type NotifyArgs = {
  action: string;
  entityType?: NotificationEntityType;
  entityId?: string;
  title: string;
  message?: string;
  href?: string;
  dedupeKey?: string;
};

function base(input: NotifyArgs): NotificationInput {
  return {
    action: input.action,
    entityType: input.entityType ?? "unknown",
    entityId: input.entityId,
    title: input.title,
    message: input.message,
    href: input.href,
    dedupeKey: input.dedupeKey,
    level: "info",
  };
}

export function notifyQueued(push: PushFn, input: NotifyArgs) {
  push({
    ...base(input),
    level: "info",
    status: "queued",
  });
}

export function notifySucceeded(push: PushFn, input: NotifyArgs) {
  push({
    ...base(input),
    level: "success",
    status: "succeeded",
  });
}

export function notifyFailed(push: PushFn, input: NotifyArgs) {
  push({
    ...base(input),
    level: "error",
    status: "failed",
  });
}
