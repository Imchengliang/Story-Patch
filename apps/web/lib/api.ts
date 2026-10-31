import type { paths } from "@canonguard/contracts";

export type ApiPaths = paths;

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8100";
