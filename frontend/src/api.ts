import type { Batch, Lead, LeadPatch } from "./types";

interface ErrorPayload {
  detail?: string;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let message = `The server returned ${response.status}. Please try again.`;
  try {
    const payload = (await response.json()) as ErrorPayload;
    if (payload.detail) message = payload.detail;
  } catch {
    // Preserve the safe generic message when the response is not JSON.
  }
  return new ApiError(message, response.status);
}

export async function createBatch(totalCards: number): Promise<Batch> {
  const response = await fetch("/api/batches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ total_cards: totalCards })
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as Batch;
}

export function uploadCard(
  batchId: string,
  file: File,
  onProgress: (percent: number) => void
): Promise<Lead> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `/api/batches/${encodeURIComponent(batchId)}/cards`);
    request.responseType = "json";
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) {
        onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    });
    request.addEventListener("load", () => {
      const payload = request.response as (Lead & ErrorPayload) | null;
      if (request.status >= 200 && request.status < 300 && payload) {
        resolve(payload);
        return;
      }
      reject(
        new ApiError(
          payload?.detail ?? `The card could not be processed (${request.status}).`,
          request.status
        )
      );
    });
    request.addEventListener("error", () => {
      reject(new ApiError("The upload was interrupted. Check your connection and retry.", 0));
    });
    request.addEventListener("timeout", () => {
      reject(new ApiError("The card took too long to process. Try a smaller image.", 0));
    });
    const form = new FormData();
    form.append("file", file, file.name);
    request.send(form);
  });
}

export async function updateLead(leadId: string, patch: LeadPatch): Promise<Lead> {
  const response = await fetch(`/api/leads/${encodeURIComponent(leadId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch)
  });
  if (!response.ok) throw await parseError(response);
  return (await response.json()) as Lead;
}

export async function removeLead(leadId: string): Promise<void> {
  const response = await fetch(`/api/leads/${encodeURIComponent(leadId)}`, {
    method: "DELETE"
  });
  if (!response.ok) throw await parseError(response);
}

function downloadName(header: string | null): string {
  const match = header?.match(/filename="?([^";]+)"?/i);
  return match?.[1] ?? "business-card-leads.xlsx";
}

export async function downloadWorkbook(batchId: string, leadIds: string[]): Promise<void> {
  const params = new URLSearchParams();
  for (const id of leadIds) params.append("lead_ids", id);
  const response = await fetch(
    `/api/batches/${encodeURIComponent(batchId)}/export.xlsx?${params.toString()}`
  );
  if (!response.ok) throw await parseError(response);

  const url = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = downloadName(response.headers.get("Content-Disposition"));
  anchor.click();
  URL.revokeObjectURL(url);
}
