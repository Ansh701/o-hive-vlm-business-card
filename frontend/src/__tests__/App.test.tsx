import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "../App";
import * as api from "../api";
import type { Lead } from "../types";

vi.mock("../api", () => ({
  createBatch: vi.fn(),
  uploadCard: vi.fn(),
  updateLead: vi.fn(),
  removeLead: vi.fn(),
  downloadWorkbook: vi.fn()
}));

const successfulLead: Lead = {
  id: "lead-1",
  batch_id: "batch-1",
  source_filename: "ada.png",
  first_name: "Ada",
  last_name: "Lovelace",
  job_title: "Engineer",
  company: "Difference Works",
  location: "London",
  phone_number: "+442079460000",
  email: "ada@example.com",
  status: "SUCCESS",
  warnings: [],
  error_message: null,
  created_at: "2026-09-19T00:00:00Z",
  updated_at: "2026-09-19T00:00:00Z"
};

function image(name: string, size = 12): File {
  return new File([new Uint8Array(size)], name, { type: "image/png" });
}

async function choose(files: File[]): Promise<void> {
  const input = screen.getByLabelText("Choose business card images");
  await userEvent.upload(input, files);
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.dataset.theme = "light";
  vi.clearAllMocks();
  vi.mocked(api.createBatch).mockResolvedValue({
    id: "batch-1",
    status: "UPLOADED",
    total_cards: 1,
    processed_cards: 0,
    successful_cards: 0,
    failed_cards: 0,
    created_at: "2026-09-19T00:00:00Z",
    completed_at: null
  });
  vi.mocked(api.uploadCard).mockImplementation((_id, _file, onProgress) => {
    onProgress(100);
    return Promise.resolve(successfulLead);
  });
  vi.mocked(api.updateLead).mockImplementation((_id, patch) => Promise.resolve({
    ...successfulLead,
    ...patch
  }));
  vi.mocked(api.removeLead).mockResolvedValue(undefined);
  vi.mocked(api.downloadWorkbook).mockResolvedValue(undefined);
});

describe("business card workflow", () => {
  it("opens on the purposeful empty upload state", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Drop business cards here" })).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("Up to 20 cards · 8 MB each")).toBeVisible();
  });

  it("validates unsupported files immediately", () => {
    render(<App />);
    const unsupported = new File(["hello"], "notes.txt", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("Choose business card images"), {
      target: { files: [unsupported] }
    });
    expect(screen.getByText("JPEG, PNG, and WEBP files only.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Extract leads" })).toBeDisabled();
  });

  it("accepts multiple files in one selection", async () => {
    render(<App />);
    await choose([image("ada.png"), image("grace.png")]);
    expect(screen.getByText("ada.png")).toBeVisible();
    expect(screen.getByText("grace.png")).toBeVisible();
    expect(screen.getByText("2 cards ready")).toBeVisible();
  });

  it("removes a selected file and revokes its preview", async () => {
    const revokeSpy = vi.spyOn(URL, "revokeObjectURL");
    render(<App />);
    await choose([image("remove.png")]);
    await userEvent.click(screen.getByRole("button", { name: "Remove remove.png" }));
    expect(screen.queryByText("remove.png")).not.toBeInTheDocument();
    expect(revokeSpy).toHaveBeenCalledWith("blob:card-preview");
  });

  it("shows real per-card upload and analysis progress", async () => {
    let finish: ((lead: Lead) => void) | undefined;
    vi.mocked(api.uploadCard).mockImplementation((_id, _file, onProgress) => {
      onProgress(62);
      return new Promise((resolve) => {
        finish = resolve;
      });
    });
    render(<App />);
    await choose([image("progress.png")]);
    await userEvent.click(screen.getByRole("button", { name: "Extract leads" }));
    expect(await screen.findByText("62% uploaded")).toBeVisible();
    expect(screen.getByText("Uploading securely…")).toBeVisible();
    act(() => finish?.(successfulLead));
    expect(await screen.findByText("1 of 1 completed")).toBeVisible();
  });

  it("preserves good leads when another card fails", async () => {
    vi.mocked(api.createBatch).mockResolvedValue({
      id: "batch-1",
      status: "UPLOADED",
      total_cards: 2,
      processed_cards: 0,
      successful_cards: 0,
      failed_cards: 0,
      created_at: "2026-09-19T00:00:00Z",
      completed_at: null
    });
    vi.mocked(api.uploadCard)
      .mockResolvedValueOnce(successfulLead)
      .mockResolvedValueOnce({
        ...successfulLead,
        id: "lead-2",
        source_filename: "blurred.png",
        first_name: null,
        status: "FAILED",
        error_message: "No contact details could be read confidently."
      });
    render(<App />);
    await choose([image("ada.png"), image("blurred.png")]);
    await userEvent.click(screen.getByRole("button", { name: "Extract leads" }));
    expect(await screen.findByText("1 lead ready")).toBeVisible();
    expect(screen.getByText("1 failed")).toBeVisible();
    expect(screen.getByText("No contact details could be read confidently.")).toBeVisible();
    expect(screen.getByText("Ada Lovelace")).toBeVisible();
  });

  it("explains a batch creation error and keeps files", async () => {
    vi.mocked(api.createBatch).mockRejectedValue(new Error("Daily allowance reached."));
    render(<App />);
    await choose([image("kept.png")]);
    await userEvent.click(screen.getByRole("button", { name: "Extract leads" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Daily allowance reached.");
    expect(screen.getByText("kept.png")).toBeVisible();
  });

  it("edits a lead with labels and persists the correction", async () => {
    render(<App />);
    await choose([image("ada.png")]);
    await userEvent.click(screen.getByRole("button", { name: "Extract leads" }));
    await screen.findByText("Ada Lovelace");
    await userEvent.click(screen.getByRole("button", { name: "Edit Ada Lovelace" }));
    const panel = screen.getByRole("dialog", { name: "Edit lead" });
    const firstName = within(panel).getByLabelText("First name");
    await userEvent.clear(firstName);
    await userEvent.type(firstName, "Augusta Ada");
    await userEvent.click(within(panel).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.updateLead).toHaveBeenCalledWith("lead-1", expect.objectContaining({ first_name: "Augusta Ada" })));
    expect(await screen.findByText("Augusta Ada Lovelace")).toBeVisible();
  });

  it("shows guidance instead of an empty results table", async () => {
    vi.mocked(api.uploadCard).mockResolvedValue({
      ...successfulLead,
      first_name: null,
      last_name: null,
      status: "FAILED",
      error_message: "No visible contact details."
    });
    render(<App />);
    await choose([image("empty.png")]);
    await userEvent.click(screen.getByRole("button", { name: "Extract leads" }));
    expect(await screen.findByRole("heading", { name: "No confident leads yet" })).toBeVisible();
    expect(screen.getByText("Try a clearer, evenly lit, uncropped image.")).toBeVisible();
  });

  it("exports only selected successful leads after generation succeeds", async () => {
    render(<App />);
    await choose([image("ada.png")]);
    await userEvent.click(screen.getByRole("button", { name: "Extract leads" }));
    await screen.findByText("Ada Lovelace");
    await userEvent.click(screen.getByRole("button", { name: "Download Excel" }));
    await waitFor(() => expect(api.downloadWorkbook).toHaveBeenCalledWith("batch-1", ["lead-1"]));
    expect(screen.getByText("Workbook download started.")).toBeVisible();
  });
});

describe("theme", () => {
  it("uses light on a first visit even when the OS might prefer dark", () => {
    render(<App />);
    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBeVisible();
  });

  it("toggles and persists the intentionally designed dark theme", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem("o-hive-theme")).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeVisible();
  });
});
