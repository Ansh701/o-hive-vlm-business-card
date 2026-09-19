import {
  AlertCircle,
  ArrowDownToLine,
  Check,
  ChevronRight,
  FileSpreadsheet,
  Image as ImageIcon,
  Info,
  Moon,
  Pencil,
  Plus,
  RotateCcw,
  ScanLine,
  ShieldCheck,
  Sparkles,
  Sun,
  Trash2,
  UploadCloud,
  X
} from "lucide-react";
import {
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";

import { createBatch, downloadWorkbook, removeLead, updateLead, uploadCard } from "./api";
import type { Lead, LeadFields, LeadPatch } from "./types";

const MAX_FILE_BYTES = 8 * 1024 * 1024;
const MAX_CARDS = 20;
const ACCEPTED_EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp"]);
const ACCEPTED_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

type Theme = "light" | "dark";
type Phase = "upload" | "processing" | "review";
type CardStage = "ready" | "invalid" | "queued" | "uploading" | "analyzing" | "done" | "failed";

interface LocalCard {
  id: string;
  file: File;
  previewUrl: string | null;
  stage: CardStage;
  progress: number;
  error: string | null;
}

type Draft = Record<keyof LeadFields, string>;

let cardSequence = 0;

function cardId(): string {
  cardSequence += 1;
  return `card-${Date.now()}-${cardSequence}`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function validationMessage(file: File): string | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!ACCEPTED_EXTENSIONS.has(extension) || !ACCEPTED_TYPES.has(file.type)) {
    return "JPEG, PNG, and WEBP files only.";
  }
  if (file.size > MAX_FILE_BYTES) return "This file is larger than the 8 MB limit.";
  return null;
}

function leadName(lead: Lead): string {
  return [lead.first_name, lead.last_name].filter(Boolean).join(" ") || "Unnamed lead";
}

function errorText(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function cardStageLabel(card: LocalCard): string {
  switch (card.stage) {
    case "ready":
      return "Ready";
    case "invalid":
      return "Needs attention";
    case "queued":
      return "Queued";
    case "uploading":
      return `${card.progress}% uploaded`;
    case "analyzing":
      return "Analyzing";
    case "done":
      return "Extracted";
    case "failed":
      return "Failed";
  }
}

function draftFromLead(lead: Lead): Draft {
  return {
    first_name: lead.first_name ?? "",
    last_name: lead.last_name ?? "",
    job_title: lead.job_title ?? "",
    company: lead.company ?? "",
    location: lead.location ?? "",
    phone_number: lead.phone_number ?? "",
    email: lead.email ?? ""
  };
}

function patchFromDraft(draft: Draft): LeadPatch {
  return Object.fromEntries(
    Object.entries(draft).map(([key, value]) => [key, value.trim() || null])
  ) as unknown as LeadPatch;
}

function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const dark = theme === "dark";
  return (
    <button
      className="icon-button theme-toggle"
      type="button"
      onClick={onToggle}
      aria-label={`Switch to ${dark ? "light" : "dark"} theme`}
    >
      <span className="theme-icon" aria-hidden="true">
        {dark ? <Sun size={18} /> : <Moon size={18} />}
      </span>
    </button>
  );
}

function WorkflowSteps({ phase }: { phase: Phase }) {
  const current = phase === "upload" ? 0 : phase === "processing" ? 0 : 1;
  const steps = ["Upload", "Review", "Export"];
  return (
    <ol className="workflow-steps" aria-label="Workflow progress">
      {steps.map((step, index) => (
        <li key={step} className={index <= current ? "is-active" : ""}>
          <span>{index + 1}</span>
          {step}
          {index < steps.length - 1 && <ChevronRight size={14} aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}

interface UploadSurfaceProps {
  dragging: boolean;
  onDrag: (dragging: boolean) => void;
  onDrop: (files: File[]) => void;
  onChoose: (files: File[]) => void;
}

function UploadSurface({ dragging, onDrag, onDrop, onChoose }: UploadSurfaceProps) {
  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    onDrag(false);
    onDrop(Array.from(event.dataTransfer.files));
  };
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    onChoose(Array.from(event.target.files ?? []));
    event.target.value = "";
  };
  return (
    <div
      className={`drop-surface ${dragging ? "is-dragging" : ""}`}
      onDragEnter={(event) => {
        event.preventDefault();
        onDrag(true);
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={(event) => {
        if (event.currentTarget === event.target) onDrag(false);
      }}
      onDrop={handleDrop}
    >
      <div className="upload-mark" aria-hidden="true">
        <UploadCloud size={28} />
      </div>
      <div>
        <p className="eyebrow">Secure bulk intake</p>
        <h1>Drop business cards here</h1>
        <p className="lede">
          Upload business-card images, extract seven useful fields, then verify every lead before export.
        </p>
      </div>
      <label className="button button-primary file-button">
        <Plus size={17} aria-hidden="true" />
        Choose cards
        <input
          className="visually-hidden"
          type="file"
          multiple
          accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp"
          aria-label="Choose business card images"
          onChange={handleChange}
        />
      </label>
      <p className="constraints">Up to 20 cards · 8 MB each</p>
    </div>
  );
}

function FileTray({
  cards,
  processing,
  onRemove
}: {
  cards: LocalCard[];
  processing: boolean;
  onRemove: (card: LocalCard) => void;
}) {
  if (!cards.length) return null;
  return (
    <section className="file-tray" aria-labelledby="selected-cards-title">
      <div className="section-heading compact">
        <div>
          <p className="eyebrow">Input queue</p>
          <h2 id="selected-cards-title">Selected cards</h2>
        </div>
        <span className="count-label">{cards.length} / {MAX_CARDS}</span>
      </div>
      <ul className="file-list">
        {cards.map((card) => (
          <li className={`file-row is-${card.stage}`} key={card.id}>
            <div className="thumbnail">
              {card.previewUrl ? (
                <img src={card.previewUrl} alt="" />
              ) : (
                <ImageIcon size={20} aria-hidden="true" />
              )}
              {card.stage === "analyzing" && <span className="scan-line" aria-hidden="true" />}
            </div>
            <div className="file-copy">
              <strong>{card.file.name}</strong>
              <span>{formatBytes(card.file.size)}</span>
              {card.error && <p className="field-error">{card.error}</p>}
            </div>
            <div className="file-state">
              <span className={`state-dot state-${card.stage}`} aria-hidden="true" />
              <span>{cardStageLabel(card)}</span>
            </div>
            {card.stage === "uploading" && (
              <div
                className="progress-track"
                role="progressbar"
                aria-label={`${card.file.name} upload progress`}
                aria-valuenow={card.progress}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <span style={{ width: `${card.progress}%` }} />
              </div>
            )}
            {!processing && (
              <button
                className="icon-button remove-file"
                type="button"
                onClick={() => onRemove(card)}
                aria-label={`Remove ${card.file.name}`}
              >
                <X size={17} />
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function ProcessingStatus({ cards }: { cards: LocalCard[] }) {
  const completed = cards.filter((card) => card.stage === "done" || card.stage === "failed").length;
  const uploading = cards.some((card) => card.stage === "uploading");
  return (
    <section className="processing-banner" aria-live="polite" aria-atomic="true">
      <div className="processing-icon" aria-hidden="true"><ScanLine size={22} /></div>
      <div>
        <p className="eyebrow">Batch in progress</p>
        <h2>{uploading ? "Uploading securely…" : "Reading contact details…"}</h2>
        <p>{completed} of {cards.length} completed · up to two cards analyzed at once</p>
      </div>
      <strong>{cards.length ? Math.round((completed / cards.length) * 100) : 0}%</strong>
    </section>
  );
}

interface LeadEditorProps {
  lead: Lead;
  onClose: () => void;
  onSaved: (lead: Lead) => void;
}

function LeadEditor({ lead, onClose, onSaved }: LeadEditorProps) {
  const [draft, setDraft] = useState(() => draftFromLead(lead));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const emailInvalid = Boolean(draft.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(draft.email));

  const change = (field: keyof Draft, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }));
    setError(null);
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (emailInvalid) return;
    setSaving(true);
    try {
      const saved = await updateLead(lead.id, patchFromDraft(draft));
      onSaved(saved);
    } catch (caught) {
      setError(errorText(caught, "The correction could not be saved. Your typed values are still here."));
    } finally {
      setSaving(false);
    }
  };

  const fields: Array<[keyof Draft, string, string]> = [
    ["first_name", "First name", "text"],
    ["last_name", "Last name", "text"],
    ["job_title", "Position / job title", "text"],
    ["company", "Company", "text"],
    ["location", "Location", "text"],
    ["phone_number", "Phone number", "tel"],
    ["email", "Email address", "email"]
  ];
  return (
    <div className="dialog-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="edit-dialog" role="dialog" aria-modal="true" aria-labelledby="edit-title">
        <div className="dialog-heading">
          <div>
            <p className="eyebrow">Human review</p>
            <h2 id="edit-title">Edit lead</h2>
            <p>{lead.source_filename}</p>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close editor"><X size={19} /></button>
        </div>
        <form onSubmit={(event) => { void submit(event); }}>
          <div className="edit-grid">
            {fields.map(([field, label, type]) => (
              <label key={field} className={field === "location" || field === "email" ? "span-two" : ""}>
                <span>{label}</span>
                <input
                  type={type}
                  value={draft[field]}
                  onChange={(event) => change(field, event.target.value)}
                  aria-invalid={field === "email" && emailInvalid}
                  maxLength={field === "location" ? 500 : field === "email" ? 320 : 300}
                />
                {field === "email" && emailInvalid && <small className="field-error">Enter a complete email or leave it blank.</small>}
              </label>
            ))}
          </div>
          {error && <p className="alert inline-alert" role="alert"><AlertCircle size={17} />{error}</p>}
          <div className="dialog-actions">
            <button className="button button-quiet" type="button" onClick={onClose}>Cancel</button>
            <button className="button button-primary" type="submit" disabled={saving || emailInvalid}>
              {saving ? "Saving…" : "Save changes"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

interface LeadReviewProps {
  leads: Lead[];
  selected: Set<string>;
  onSelect: (id: string) => void;
  onEdit: (lead: Lead) => void;
  onRemove: (lead: Lead) => void;
}

function LeadReview({ leads, selected, onSelect, onEdit, onRemove }: LeadReviewProps) {
  const exportable = leads.filter((lead) => lead.status !== "FAILED");
  if (!exportable.length) {
    return (
      <section className="zero-results">
        <div className="empty-result-icon"><ScanLine size={25} /></div>
        <h2>No confident leads yet</h2>
        <p>Try a clearer, evenly lit, uncropped image.</p>
      </section>
    );
  }
  return (
    <section className="review-panel" aria-labelledby="review-heading">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Review workspace</p>
          <h2 id="review-heading">Verify before export</h2>
          <p>Model output stays editable. Blank fields mean the card did not show a confident value.</p>
        </div>
        <span className="count-label">{selected.size} selected</span>
      </div>
      <div className="lead-table-wrap">
        <table className="lead-table">
          <thead>
            <tr>
              <th><span className="visually-hidden">Select</span></th>
              <th>Person</th>
              <th>Company / role</th>
              <th>Contact</th>
              <th>Status</th>
              <th><span className="visually-hidden">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {exportable.map((lead) => (
              <tr key={lead.id}>
                <td data-label="Select">
                  <input
                    className="row-checkbox"
                    type="checkbox"
                    checked={selected.has(lead.id)}
                    onChange={() => onSelect(lead.id)}
                    aria-label={`Select ${leadName(lead)}`}
                  />
                </td>
                <td data-label="Person">
                  <strong>{leadName(lead)}</strong>
                  <span>{lead.location || "Location not shown"}</span>
                </td>
                <td data-label="Company / role">
                  <strong>{lead.company || "Company not shown"}</strong>
                  <span>{lead.job_title || "Title not shown"}</span>
                </td>
                <td data-label="Contact">
                  <strong>{lead.email || "Email not shown"}</strong>
                  <span>{lead.phone_number || "Phone not shown"}</span>
                </td>
                <td data-label="Status">
                  <span className={`status-label status-${lead.status.toLowerCase()}`}>
                    {lead.status === "PARTIAL" ? "Needs review" : "Ready"}
                  </span>
                  {lead.warnings.length > 0 && <small>{lead.warnings.length} warning{lead.warnings.length === 1 ? "" : "s"}</small>}
                </td>
                <td className="row-actions">
                  <button className="icon-button" type="button" onClick={() => onEdit(lead)} aria-label={`Edit ${leadName(lead)}`}><Pencil size={16} /></button>
                  <button className="icon-button danger" type="button" onClick={() => onRemove(lead)} aria-label={`Remove ${leadName(lead)}`}><Trash2 size={16} /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => localStorage.getItem("o-hive-theme") === "dark" ? "dark" : "light");
  const [phase, setPhase] = useState<Phase>("upload");
  const [dragging, setDragging] = useState(false);
  const [cards, setCards] = useState<LocalCard[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Lead | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportMessage, setExportMessage] = useState<string | null>(null);
  const previewUrls = useRef(new Set<string>());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("o-hive-theme", theme);
    const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    meta?.setAttribute("content", theme === "dark" ? "#101715" : "#f1eee7");
  }, [theme]);

  useEffect(() => () => {
    for (const url of previewUrls.current) URL.revokeObjectURL(url);
  }, []);

  const addFiles = (files: File[]) => {
    setGlobalError(null);
    setCards((current) => {
      const room = Math.max(0, MAX_CARDS - current.length);
      const accepted = files.slice(0, room).map((file): LocalCard => {
        const error = validationMessage(file);
        const previewUrl = ACCEPTED_TYPES.has(file.type) ? URL.createObjectURL(file) : null;
        if (previewUrl) previewUrls.current.add(previewUrl);
        return {
          id: cardId(),
          file,
          previewUrl,
          stage: error ? "invalid" : "ready",
          progress: 0,
          error
        };
      });
      if (files.length > room) {
        setGlobalError(`Only ${MAX_CARDS} cards can be processed in one batch.`);
      }
      return [...current, ...accepted];
    });
  };

  const removeLocalCard = (card: LocalCard) => {
    if (card.previewUrl) {
      URL.revokeObjectURL(card.previewUrl);
      previewUrls.current.delete(card.previewUrl);
    }
    setCards((current) => current.filter((candidate) => candidate.id !== card.id));
  };

  const updateCard = (id: string, changes: Partial<LocalCard>) => {
    setCards((current) => current.map((card) => card.id === id ? { ...card, ...changes } : card));
  };

  const processCards = async () => {
    const ready = cards.filter((card) => card.stage === "ready");
    if (!ready.length) return;
    setGlobalError(null);
    setExportMessage(null);
    try {
      const batch = await createBatch(ready.length);
      setBatchId(batch.id);
      setPhase("processing");
      setCards((current) => current.map((card) => card.stage === "ready" ? { ...card, stage: "queued" } : card));
      let cursor = 0;
      const worker = async () => {
        while (cursor < ready.length) {
          const card = ready[cursor];
          cursor += 1;
          if (!card) return;
          updateCard(card.id, { stage: "uploading", progress: 0 });
          try {
            const lead = await uploadCard(batch.id, card.file, (progress) => {
              updateCard(card.id, {
                progress,
                stage: progress >= 100 ? "analyzing" : "uploading"
              });
            });
            const failed = lead.status === "FAILED";
            updateCard(card.id, {
              stage: failed ? "failed" : "done",
              progress: 100,
              error: failed ? lead.error_message : null
            });
            setLeads((current) => [...current, lead]);
            if (!failed) setSelected((current) => new Set(current).add(lead.id));
          } catch (caught) {
            updateCard(card.id, {
              stage: "failed",
              error: errorText(caught, "This card could not be processed.")
            });
          }
        }
      };
      await Promise.all(Array.from({ length: Math.min(2, ready.length) }, worker));
      setPhase("review");
    } catch (caught) {
      setGlobalError(errorText(caught, "The batch could not be started. Your selected files are still here."));
      setPhase("upload");
    }
  };

  const exportable = useMemo(() => leads.filter((lead) => lead.status !== "FAILED"), [leads]);
  const failedCount = cards.filter((card) => card.stage === "failed").length;
  const reviewCount = exportable.filter((lead) => lead.status === "PARTIAL").length;
  const completedCount = cards.filter((card) => card.stage === "done" || card.stage === "failed").length;
  const validCount = cards.filter((card) => card.stage === "ready").length;

  const toggleSelected = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const removeReviewedLead = async (lead: Lead) => {
    const index = leads.findIndex((candidate) => candidate.id === lead.id);
    setLeads((current) => current.filter((candidate) => candidate.id !== lead.id));
    setSelected((current) => {
      const next = new Set(current);
      next.delete(lead.id);
      return next;
    });
    try {
      await removeLead(lead.id);
    } catch (caught) {
      setLeads((current) => {
        const restored = [...current];
        restored.splice(Math.max(0, index), 0, lead);
        return restored;
      });
      setSelected((current) => new Set(current).add(lead.id));
      setGlobalError(errorText(caught, "The lead could not be removed."));
    }
  };

  const saveEditedLead = (saved: Lead) => {
    setLeads((current) => current.map((lead) => lead.id === saved.id ? saved : lead));
    setEditing(null);
  };

  const exportSelected = async () => {
    if (!batchId || !selected.size) return;
    setExporting(true);
    setExportMessage(null);
    try {
      await downloadWorkbook(batchId, Array.from(selected));
      setExportMessage("Workbook download started.");
    } catch (caught) {
      setGlobalError(`${errorText(caught, "We couldn't create the workbook.")} Your leads are still safe.`);
    } finally {
      setExporting(false);
    }
  };

  const reset = () => {
    for (const card of cards) {
      if (card.previewUrl) URL.revokeObjectURL(card.previewUrl);
    }
    previewUrls.current.clear();
    setCards([]);
    setLeads([]);
    setSelected(new Set());
    setBatchId(null);
    setGlobalError(null);
    setExportMessage(null);
    setPhase("upload");
  };

  return (
    <div className="app-shell">
      <header className="app-header">
        <a className="brand" href="#main" aria-label="O-HIVE Card Leads home">
          <span className="brand-glyph" aria-hidden="true">O</span>
          <span><strong>O-HIVE</strong><small>Card leads</small></span>
        </a>
        <div className="header-actions">
          <span className="privacy-chip"><ShieldCheck size={14} /> Images deleted after extraction</span>
          <ThemeToggle theme={theme} onToggle={() => setTheme((current) => current === "light" ? "dark" : "light")} />
        </div>
      </header>

      <main id="main" className="main-content">
        <div className="workspace-heading">
          <div>
            <p className="eyebrow"><Sparkles size={13} /> Document intelligence workspace</p>
            <h1>Business card <span>→</span> lead list</h1>
          </div>
          <WorkflowSteps phase={phase} />
        </div>

        {globalError && (
          <div className="alert" role="alert">
            <AlertCircle size={18} aria-hidden="true" />
            <span>{globalError}</span>
            <button type="button" onClick={() => setGlobalError(null)} aria-label="Dismiss error"><X size={16} /></button>
          </div>
        )}

        {phase === "upload" && (
          <div className="upload-layout">
            <UploadSurface dragging={dragging} onDrag={setDragging} onDrop={addFiles} onChoose={addFiles} />
            <aside className="intake-notes" aria-label="How extraction works">
              <p className="eyebrow">Before you begin</p>
              <h2>Visible details only.</h2>
              <p>The model is instructed not to invent missing names, locations, titles, or contact details.</p>
              <ul>
                <li><Check size={15} /> JPEG, PNG, or WEBP</li>
                <li><Check size={15} /> One card per image</li>
                <li><Check size={15} /> Structured data retained; raw image discarded</li>
              </ul>
              <div className="privacy-note"><Info size={16} /><p><strong>Privacy note</strong>Images are held in memory only for validation and AWS extraction. The database stores the resulting lead, not the card image.</p></div>
            </aside>
          </div>
        )}

        {(phase === "upload" || phase === "processing") && (
          <FileTray cards={cards} processing={phase === "processing"} onRemove={removeLocalCard} />
        )}

        {phase === "upload" && cards.length > 0 && (
          <div className="action-dock">
            <div>
              <strong>{validCount} card{validCount === 1 ? "" : "s"} ready</strong>
              <span>{cards.length - validCount ? `${cards.length - validCount} need attention` : "Validation complete"}</span>
            </div>
            <button className="button button-primary" type="button" onClick={() => void processCards()} disabled={!validCount}>
              <ScanLine size={18} /> Extract leads
            </button>
          </div>
        )}

        {phase === "processing" && (
          <>
            <ProcessingStatus cards={cards} />
            <p className="sr-status" aria-live="polite">{completedCount} of {cards.length} completed</p>
          </>
        )}

        {phase === "review" && (
          <>
            <section className="result-summary" aria-live="polite">
              <div className="summary-mark"><Check size={21} /></div>
              <div className="summary-intro">
                <p className="eyebrow">Extraction complete</p>
                <h2>{completedCount} of {cards.length} completed</h2>
              </div>
              <dl>
                <div><dt>Ready</dt><dd>{exportable.length} lead{exportable.length === 1 ? "" : "s"} ready</dd></div>
                <div><dt>Review</dt><dd>{reviewCount} need{reviewCount === 1 ? "s" : ""} review</dd></div>
                <div><dt>Failed</dt><dd>{failedCount} failed</dd></div>
              </dl>
            </section>

            {failedCount > 0 && (
              <section className="failure-list" aria-labelledby="failed-heading">
                <h2 id="failed-heading">Cards that need another try</h2>
                {cards.filter((card) => card.stage === "failed").map((card) => (
                  <div key={card.id}><AlertCircle size={17} /><p><strong>{card.file.name}</strong>{card.error ?? "This image could not be extracted."}</p></div>
                ))}
              </section>
            )}

            <LeadReview leads={leads} selected={selected} onSelect={toggleSelected} onEdit={setEditing} onRemove={(lead) => void removeReviewedLead(lead)} />

            <div className="export-dock">
              <button className="button button-quiet" type="button" onClick={reset}><RotateCcw size={17} /> Start another batch</button>
              <div className="export-actions">
                {exportMessage && <span className="success-message" role="status"><Check size={15} />{exportMessage}</span>}
                <button className="button button-export" type="button" onClick={() => void exportSelected()} disabled={!selected.size || exporting}>
                  {exporting ? <FileSpreadsheet size={18} /> : <ArrowDownToLine size={18} />}
                  {exporting ? "Preparing workbook…" : "Download Excel"}
                </button>
              </div>
            </div>
          </>
        )}
      </main>

      <footer>
        <span>O-HIVE Assignment 1</span>
        <span>Qwen VLM · human-reviewed export</span>
      </footer>

      {editing && <LeadEditor lead={editing} onClose={() => setEditing(null)} onSaved={saveEditedLead} />}
    </div>
  );
}
