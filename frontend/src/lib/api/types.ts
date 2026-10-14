// Shared API contracts. Kept deliberately small: extended as backend endpoints land.

export type DocumentStatus = "uploaded" | "processing" | "ready" | "failed";

export interface DocumentSummary {
  id: string;
  name: string;
  status: DocumentStatus;
  createdAt: string; // ISO 8601
  sizeBytes: number;
}

export interface ApiErrorBody {
  detail?: string;
}
