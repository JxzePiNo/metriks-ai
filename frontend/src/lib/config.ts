const DEFAULT_API_URL = "http://localhost:8000";

/** Base URL of the backend API, without a trailing slash. */
export function getApiUrl(): string {
  // Must be referenced statically so Next.js can inline it in the client bundle.
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim() || DEFAULT_API_URL;

  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new Error(`NEXT_PUBLIC_API_URL is not a valid absolute URL: "${raw}"`);
  }
  return url.toString().replace(/\/+$/, "");
}
