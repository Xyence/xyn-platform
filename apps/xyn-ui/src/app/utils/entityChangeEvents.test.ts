import { describe, expect, it, vi } from "vitest";

import {
  emitEntityChange,
  inferEntityChangeFromDraftPayload,
  inferEntityChangeFromPrompt,
  inferEntityListPrompt,
  XYN_ENTITY_CHANGE_EVENT,
} from "./entityChangeEvents";

describe("entityChangeEvents", () => {
  it("infers palette CRUD entity changes from prompts", () => {
    expect(inferEntityChangeFromPrompt("create device named router-1")).toEqual({
      entityKey: "devices",
      operation: "create",
      source: "palette",
    });
    expect(inferEntityChangeFromPrompt("rename device router-1 to router-core")).toEqual({
      entityKey: "devices",
      operation: "update",
      source: "palette",
    });
    expect(inferEntityChangeFromPrompt("delete location st-louis")).toEqual({
      entityKey: "locations",
      operation: "delete",
      source: "palette",
    });
  });

  it("infers watched list prompts", () => {
    expect(inferEntityListPrompt("show devices")).toEqual({ entityKey: "devices", prompt: "show devices" });
    expect(inferEntityListPrompt("list location")).toEqual({ entityKey: "locations", prompt: "list location" });
    expect(inferEntityListPrompt("create device")).toBeNull();
  });

  it("infers agent CRUD changes from draft payloads", () => {
    expect(
      inferEntityChangeFromDraftPayload({
        __operation: "execute_generated_app_crud",
        structured_operation: { operation: "update", entity_key: "devices" },
      })
    ).toEqual({
      entityKey: "devices",
      operation: "update",
      source: "agent",
    });
  });

  it("dispatches the browser event", () => {
    const spy = vi.fn();
    window.addEventListener(XYN_ENTITY_CHANGE_EVENT, spy as EventListener);
    emitEntityChange({ entityKey: "device", operation: "delete", source: "palette" });
    expect(spy).toHaveBeenCalledTimes(1);
    const event = spy.mock.calls[0][0] as CustomEvent;
    expect(event.detail).toEqual({ entityKey: "devices", operation: "delete", source: "palette" });
    window.removeEventListener(XYN_ENTITY_CHANGE_EVENT, spy as EventListener);
  });
});
