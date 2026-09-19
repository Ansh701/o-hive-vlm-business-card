export type BatchStatus =
  | "UPLOADED"
  | "PROCESSING"
  | "PARTIAL_SUCCESS"
  | "COMPLETED"
  | "FAILED";

export type LeadStatus = "QUEUED" | "PROCESSING" | "SUCCESS" | "PARTIAL" | "FAILED";

export interface Batch {
  id: string;
  status: BatchStatus;
  total_cards: number;
  processed_cards: number;
  successful_cards: number;
  failed_cards: number;
  created_at: string;
  completed_at: string | null;
}

export interface LeadFields {
  first_name: string | null;
  last_name: string | null;
  job_title: string | null;
  company: string | null;
  location: string | null;
  phone_number: string | null;
  email: string | null;
}

export interface Lead extends LeadFields {
  id: string;
  batch_id: string;
  source_filename: string;
  status: LeadStatus;
  warnings: string[];
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export type LeadPatch = LeadFields;
