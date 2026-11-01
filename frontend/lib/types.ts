export type Evidence = { kind: string; text: string };
export type Issue = { severity: string; text: string };
export type RoleInfo = { column: string; source: string; alternatives: string[]; unit?: string | null };

export type Method = { id: string; name: string; status: "available" | "planned" | "unsuitable"; reason?: string };

export type Profile = {
  category: string;
  category_label: string;
  confidence: number;
  ambiguous: boolean;
  needs_confirmation: boolean;
  alternatives: { category: string; label: string; score: number }[];
  evidence: Evidence[];
  roles: Record<string, RoleInfo>;
  columns_found: string[];
  quality_issues: Issue[];
  coverage?: {
    n_rows: number;
    n_valid: number;
    baseline_days?: number;
    median_cadence_s?: number;
    n_gaps?: number;
    largest_gap_days?: number;
    duty_cycle?: number;
    time_start?: number;
    time_end?: number;
  } | null;
  time?: { format: string; unit?: string; offset_jd?: number | null; confidence: number } | null;
  flux_kind?: string | null;
  applicable_methods: Method[];
  limitations: string[];
  notes: string[];
  file_format: string;
  n_rows: number;
  header: Record<string, unknown>;
};

export type ModuleParam = {
  name: string;
  type: string;
  default: unknown;
  description: string;
  advanced: boolean;
  min?: number | null;
  max?: number | null;
  choices?: string[] | null;
};

export type ModuleInfo = {
  id: string;
  name: string;
  status: string;
  description: string;
  assumptions: string[];
  limitations: string[];
  prerequisites: string[];
  parameters: ModuleParam[];
};

export type Dataset = {
  id: string;
  source: "upload" | "archive";
  name: string;
  sha256: string;
  size_bytes: number;
  created_at: number;
  provenance: Record<string, unknown>;
  profile: Profile;
  mapping: Record<string, string>;
  analysis_options: { module: ModuleInfo; status: string; reason?: string }[];
};

export type Param = { value: number; err: number | null; method: string; range_over_b?: [number, number] };
export type Check = { id: string; status: "pass" | "warn" | "fail" | "na"; detail: string };

export type Candidate = {
  rank: number;
  kind: string;
  status_text: string;
  period: number;
  t0: number;
  duration: number;
  depth: number;
  depth_snr: number;
  sde: number;
  below_threshold: boolean;
  n_transits_observed: number;
  t0_absolute_jd: number | null;
  vetting: { checks: Check[]; n_fail: number; n_warn: number; catalog_match: { name: string; status: string } | null };
  fit: {
    ok: boolean;
    params: Record<string, Param>;
    reduced_chi2: number;
    flags: string[];
    assumptions: string[];
    limb_darkening: { u: number[]; note: string };
    derived: {
      depth_model_ppm: number;
      duration_total_hours: number;
      stellar_density_solar: number;
      planet_radius_earth: { value: number; err: number; stellar_radius_rsun: number; note: string } | null;
      radius_note?: string;
    };
    mcmc?: { converged?: boolean; error?: string };
  } | null;
  folded: { phase: number[]; flux: number[]; err: number[] };
  model: { phase: number[]; flux: number[] } | null;
};

export type AnalysisResult = {
  candidates: Candidate[];
  warnings: string[];
  summary: string;
  series: {
    raw: { time: number[]; flux: number[] };
    flattened: { time: number[]; flux: number[] };
    trend: { time: number[]; flux: number[] };
    time_format: string;
    time_offset_jd: number | null;
  };
  search?: { period_range?: [number, number]; sde_threshold?: number };
  periodograms: { rank: number; period: number[]; power: number[]; sde_flattened: number[] }[];
  provenance: Record<string, any>;
};

export type Analysis = {
  id: string;
  dataset_id: string;
  module_id: string;
  params: Record<string, unknown>;
  status: "queued" | "running" | "succeeded" | "failed";
  stage: string;
  progress: number;
  error: string | null;
  created_at: number;
  finished_at: number | null;
  result?: AnalysisResult;
};

export type ArchiveErr = { source: string; message: string; retriable: boolean };
export type Prov = { source: string; retrieved_at: number; from_cache: boolean };

export type SearchResult = {
  kind: string;
  host: string;
  key: string;
  planets: string[];
  source: string;
  note?: string;
  candidates?: string[];
};

export type Observation = {
  obsid: string;
  mission: string;
  pipeline: string | null;
  target_name: string;
  sequence: number | null;
  exposure_s: number | null;
  start_date: string | null;
  end_date: string | null;
  analysis_supported: boolean;
  unsupported_reason: string | null;
};

export type Val = { value: number; unit: string | null; err_plus?: number | null; err_minus?: number | null; calculated?: boolean; estimate?: { method: string; model_version?: string; training_rows?: number; features_used?: number; uncertainty_note: string } } | null;

export type TargetDetail = {
  key: string;
  label: string;
  star: {
    name: string;
    teff: Val;
    radius: Val;
    mass: Val;
    distance: Val;
    ids: Record<string, string>;
    reference?: string | null;
  } | null;
  position: { ra_deg: number | null; dec_deg: number | null };
  aliases: string[];
  published_planets: {
    name: string;
    status: string;
    period: Val;
    radius: Val;
    mass: Val;
    transit_duration: Val;
    transit_depth?: Val;
    discovery: { method?: string; year?: number; facility?: string };
    reference?: string | null;
  }[];
  catalog_candidates: {
    name: string;
    catalog: string;
    disposition: string | null;
    status: string;
    period: number | null;
    depth_ppm: number | null;
    radius_earth: number | null;
  }[];
  observations: Record<string, Observation[]>;
  n_observations: number;
  errors: ArchiveErr[];
  provenance: Prov[];
  estimate_model: { version?: string; trained_at?: string; source?: string; estimates: number } | null;
  notes: string[];
};
