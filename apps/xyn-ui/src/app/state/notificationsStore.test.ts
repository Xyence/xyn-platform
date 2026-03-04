import { describe, expect, it } from "vitest";
import { makeNotification, notificationsReducer } from "./notificationsStore";

describe("notificationsStore", () => {
  it("dedupes by dedupeKey and updates existing item", () => {
    const first = notificationsReducer(
      { notifications: [] },
      {
        type: "PUSH",
        payload: {
          level: "info",
          title: "Queued",
          status: "queued",
          dedupeKey: "draft.generate:1",
        },
      }
    );

    const second = notificationsReducer(first, {
      type: "PUSH",
      payload: {
        level: "success",
        title: "Finished",
        status: "succeeded",
        dedupeKey: "draft.generate:1",
      },
    });

    expect(second.notifications).toHaveLength(1);
    expect(second.notifications[0].status).toBe("succeeded");
    expect(second.notifications[0].version).toBeGreaterThan(1);
  });

  it("tracks unread count through reducer actions", () => {
    const a = makeNotification({ level: "info", title: "A" });
    const b = makeNotification({ level: "error", title: "B" });

    let state = notificationsReducer({ notifications: [] }, { type: "HYDRATE", items: [a, b] });
    expect(state.notifications.filter((item) => item.unread)).toHaveLength(2);

    state = notificationsReducer(state, { type: "MARK_READ", id: a.id });
    expect(state.notifications.filter((item) => item.unread)).toHaveLength(1);

    state = notificationsReducer(state, { type: "MARK_ALL_READ" });
    expect(state.notifications.filter((item) => item.unread)).toHaveLength(0);
  });
});
