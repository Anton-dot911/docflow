import { z } from "zod";
import { ApiError } from "./review.ts";
import { demoSampleSchema, type DemoSample } from "./schemas.ts";

// Client for the T9 /demo entry page (see docs/PLAN.md's GET /api/demo/samples
// contract). The Vite dev server proxies /api to the FastAPI backend.

const demoSamplesSchema = z.array(demoSampleSchema);

export async function fetchDemoSamples(): Promise<DemoSample[]> {
  const response = await fetch("/api/demo/samples");
  if (!response.ok) {
    throw new ApiError(`GET demo samples failed with status ${response.status}`, response.status);
  }
  return parseDemoSamples(await response.json());
}

// Split out of fetchDemoSamples so response validation is unit-testable.
export function parseDemoSamples(data: unknown): DemoSample[] {
  return demoSamplesSchema.parse(data);
}
