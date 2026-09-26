import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, apiUrl, setUnauthorizedHandler } from "@/lib/api";
import { defaultSuffix, effectiveSuffix, normalizeCodec, outputFolder } from "@/lib/naming";
import { getIn, pathKey, samePath, setIn, startsWith } from "@/lib/path";
import { basename, duration, plural, relativeTime, sourceLabel } from "@/lib/utils";

describe("path helpers", () => {
  it("reads and writes nested values immutably", () => {
    const data = { a: [{ b: 1 }] };
    const next = setIn(data, ["a", 0, "b"], 2);
    expect(getIn(next, ["a", 0, "b"])).toBe(2);
    expect(data.a[0].b).toBe(1);
    expect(setIn({}, ["x", 0], "y")).toEqual({ x: ["y"] });
    expect(setIn({ a: 1, b: 2 }, ["a"], undefined)).toEqual({ b: 2 });
    expect(getIn(null, ["a"])).toBeUndefined();
  });

  it("compares paths", () => {
    expect(pathKey(["a", 0])).toBe("a.0");
    expect(samePath(["a", 0], ["a", "0"])).toBe(true);
    expect(startsWith(["a", 0, "b"], ["a", 0])).toBe(true);
    expect(startsWith(["a"], ["a", 0])).toBe(false);
  });
});

describe("output folder naming (mirrors the backend)", () => {
  it("derives suffixes", () => {
    expect(defaultSuffix({ type: "audio_language", languages: [{ code: "eng" }, "deu"] })).toBe("deu-eng");
    expect(defaultSuffix({ type: "resolution", min_height: "2160p" })).toBe("2160p-plus");
    expect(defaultSuffix({ type: "resolution", max_height: 1080 })).toBe("max-1080p");
    expect(defaultSuffix({ type: "resolution", min_height: 720, max_height: 1080 })).toBe("720p-1080p");
    expect(defaultSuffix({ type: "video_codec", codecs: ["x265", "hevc", "AVC"] })).toBe("h264-hevc");
    expect(defaultSuffix({ type: "audio_channels", min_channels: 6 })).toBe("6ch");
    expect(effectiveSuffix({ type: "audio_language", languages: ["deu"], invert: true })).toBe("not-deu");
    expect(effectiveSuffix({ type: "audio_language", languages: ["deu"], suffix: "german" })).toBe("german");
    expect(normalizeCodec(" DDP ")).toBe("eac3");
  });

  it("resolves the output folder", () => {
    const library = { name: "TV Shows" };
    const sym = { filters: [{ type: "audio_language", languages: ["deu"] }] };
    expect(outputFolder({ output_path: "/out/" }, library, sym)).toBe("/out/tv-shows-deu");
    expect(outputFolder({}, { ...library, output_path: "/lib" }, { ...sym, name: "german" })).toBe("/lib/german");
    expect(outputFolder({}, library, { ...sym, output_path: "/abs" })).toBe("/abs");
    expect(outputFolder({}, library, sym)).toBeNull();
  });
});

describe("formatting", () => {
  it("formats durations and counts", () => {
    expect(duration(0.25)).toBe("250 ms");
    expect(duration(12.34)).toBe("12.3 s");
    expect(duration(125)).toBe("2 min 5 s");
    expect(duration(7200)).toBe("2 h 0 min");
    expect(duration(3 * 86400)).toBe("3 d 0 h");
    expect(duration(null)).toBe("—");
    expect(plural(1, "scan")).toBe("1 scan");
    expect(plural(2, "scan")).toBe("2 scans");
    expect(basename("/a/b/c/")).toBe("c");
  });

  it("formats relative times", () => {
    const now = Date.UTC(2026, 0, 1);
    expect(relativeTime(null)).toBe("never");
    expect(relativeTime(now / 1000 - 5, now)).toBe("just now");
    expect(relativeTime(now / 1000 - 120, now)).toMatch(/2 minutes ago/);
    expect(relativeTime(now / 1000 + 3600, now)).toMatch(/in 1 hour/);
  });

  it("labels trigger sources", () => {
    expect(sourceLabel("ui:admin")).toBe("Manual (admin)");
    expect(sourceLabel("webhook:sonarr, schedule")).toBe("Webhook (sonarr), Schedule");
    expect(sourceLabel("api")).toBe("API");
    expect(sourceLabel("cli")).toBe("Command line");
    expect(sourceLabel("ui")).toBe("Manual");
    expect(sourceLabel("other")).toBe("other");
  });
});

describe("api client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setUnauthorizedHandler(null);
  });

  it("sends the CSRF header and JSON bodies", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.post("scans", { dry_run: true })).resolves.toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("api/v1/scans");
    expect(init.headers["X-Requested-With"]).toBe("boomarr");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe('{"dry_run":true}');
  });

  it("maps errors and reports expired sessions", async () => {
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    const body = { detail: "Invalid", errors: [{ loc: ["a"], msg: "bad" }] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 401 })));
    const error = await api.get("dashboard").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).errors).toEqual([{ loc: ["a"], msg: "bad" }]);
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("handles plain text and empty responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("boom", { status: 500, statusText: "Server Error" })));
    await expect(api.get("x")).rejects.toThrow("Server Error");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(api.put("x", {})).resolves.toBeNull();
  });

  it("builds absolute URLs", () => {
    expect(apiUrl("events")).toMatch(/\/api\/v1\/events$/);
  });
});
