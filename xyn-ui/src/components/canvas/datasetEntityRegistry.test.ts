import { describe, expect, it } from "vitest";
import { getEntityTypeForDataset, getOpenDetailTarget } from "./datasetEntityRegistry";

describe("datasetEntityRegistry", () => {
  it("maps known datasets to entity types", () => {
    expect(getEntityTypeForDataset("artifacts")).toBe("artifact");
    expect(getEntityTypeForDataset("ems_devices")).toBe("device");
    expect(getEntityTypeForDataset("ems_registrations")).toBe("registration");
    expect(getEntityTypeForDataset("runs")).toBe("run");
    expect(getEntityTypeForDataset("workspaces")).toBe("workspace");
  });

  it("builds open-detail target for known dataset", () => {
    expect(getOpenDetailTarget("artifacts", { slug: "core.authn-jwt" }, "slug")).toEqual({
      entity_type: "artifact",
      entity_id: "core.authn-jwt",
    });
  });

  it("falls back to generic record target for unknown dataset", () => {
    expect(getOpenDetailTarget("unknown_records", { id: "r-123" }, "id")).toEqual({
      entity_type: "record",
      entity_id: "r-123",
      dataset: "unknown_records",
    });
  });
});
