import { describe, expect, it } from "vitest";
import { cn } from "./cn";

describe("cn", () => {
  it("joins truthy class names", () => {
    expect(cn("a", false && "b", "c", null, undefined)).toBe("a c");
  });

  it("returns empty string for no classes", () => {
    expect(cn(false, null, undefined)).toBe("");
  });
});
