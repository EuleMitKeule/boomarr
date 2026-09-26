import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { FilterCard } from "@/components/filter-editor";
import { TagInput } from "@/components/form";
import { OutcomeBadge, scanOutcome } from "@/components/scan-summary";
import type { ScanRecord } from "@/lib/types";

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <TooltipPrimitive.Provider>
        <MemoryRouter>{children}</MemoryRouter>
      </TooltipPrimitive.Provider>
    </QueryClientProvider>
  );
}

const base: ScanRecord = {
  started_at: 0,
  finished_at: 1,
  duration_seconds: 1,
  error: null,
  dry_run: false,
  force: false,
  source: "schedule",
  cancelled: false,
};

describe("scan outcome", () => {
  it("prioritises failures", () => {
    expect(scanOutcome({ ...base, error: "x" }).label).toBe("Failed");
    expect(scanOutcome({ ...base, cancelled: true }).label).toBe("Cancelled");
    expect(scanOutcome({ ...base, dry_run: true }).label).toBe("Dry run");
    expect(scanOutcome(base).label).toBe("Success");
    render(<OutcomeBadge scan={{ ...base, error: "x" }} />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });
});

describe("TagInput", () => {
  it("adds, normalises and removes items", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TagInput value={["A"]} onChange={onChange} normalize={(v) => v.toUpperCase()} />);
    await user.type(screen.getByRole("textbox"), "b{Enter}");
    expect(onChange).toHaveBeenLastCalledWith(["A", "B"]);
    await user.type(screen.getByRole("textbox"), "a,");
    expect(onChange).toHaveBeenCalledTimes(1); // duplicates are ignored
    await user.click(screen.getByRole("button", { name: "Remove A" }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });
});

describe("FilterCard", () => {
  it("edits a resolution filter", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      wrap(
        <FilterCard filter={{ type: "resolution", min_height: null }} onChange={onChange} onRemove={vi.fn()} errors={["min_height: bad"]} />,
      ),
    );
    expect(screen.getByText("Resolution")).toBeInTheDocument();
    expect(screen.getByText("min_height: bad")).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText("min, e.g. 2160"), "7");
    expect(onChange).toHaveBeenLastCalledWith({ type: "resolution", min_height: 7 });
    await user.click(screen.getByRole("switch", { name: "Invert filter" }));
    expect(onChange).toHaveBeenLastCalledWith({ type: "resolution", min_height: null, invert: true });
  });
});
