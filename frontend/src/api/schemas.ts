import { z } from "zod";

// Wire-contract schemas for responses crossing the HTTP boundary from the
// FastAPI backend. Inlined here (the scaffolder's ts-fullstack template kept
// these in a shared workspace package shared with a Fastify service; DocFlow's
// backend is Python, so the web app owns its own copy of the contract).

export const healthResponseSchema = z.object({
  status: z.literal("ok"),
  commit: z.string(),
});

export type HealthResponse = z.infer<typeof healthResponseSchema>;
