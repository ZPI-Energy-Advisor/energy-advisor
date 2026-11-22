import { describe, expect, it } from "vitest";
import { createResponseCache } from "./responseCache";

describe("createResponseCache", () => {
  it("usuwa najdawniej używaną odpowiedź po przekroczeniu limitu", () => {
    const cache = createResponseCache(2);
    cache.set("a", 1);
    cache.set("b", 2);
    cache.touch("a");
    cache.set("c", 3);

    expect([cache.get("a"), cache.get("b"), cache.get("c"), cache.size]).toEqual([1, undefined, 3, 2]);
  });

  it("czyści wszystkie odpowiedzi", () => {
    const cache = createResponseCache();
    cache.set("a", 1);
    cache.clear();

    expect(cache.get("a")).toBeUndefined();
  });
});
