import { describe, expect, it } from "vitest";
import { groupBySection, sectionOf } from "./sections";

describe("sections", () => {
  it("places each kind of item", () => {
    expect(sectionOf({ source_type: "academic_paper", area: "quant_finance" } as never)).toBe("research");
    expect(sectionOf({ source_type: "market_move", area: "markets_macro" } as never)).toBe("market");
    expect(sectionOf({ source_type: "official", area: null } as never)).toBe("market");
    expect(sectionOf({ source_type: "discussion", area: "quant_finance" } as never)).toBe("tech");
    expect(sectionOf({ source_type: "news", area: "ai_ml" } as never)).toBe("tech");
    expect(sectionOf({ source_type: "news", area: "careers" } as never)).toBe("news");
    expect(sectionOf({ source_type: "news", area: "quant_finance", section: "market" } as never)).toBe("market"); // backend wins
  });
  it("groups in Market, Research, News, Tech order and keeps ranking inside groups", () => {
    const items = [
      { id: "p1", source_type: "academic_paper", area: "ai_ml" },
      { id: "m1", source_type: "market_move", area: "markets_macro" },
      { id: "p2", source_type: "academic_paper", area: "quant_finance" },
      { id: "t1", source_type: "lab_blog", area: "ai_ml" },
    ] as never[];
    const g = groupBySection(items);
    expect(g.map((x) => x.key)).toEqual(["market", "research", "tech"]);
    expect(g[1].items.map((i: { id: string }) => i.id)).toEqual(["p1", "p2"]);
  });
});
