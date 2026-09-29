# List shapes — what each purchased list contains, and its traps

One section per list source. This is the data-shape knowledge that must survive next to the
adapters: coverage facts, semantics, and the traps that make a filter lie. Update this file
whenever a new list arrives or a documented fact changes. Profiled 2026-07-11 unless noted.

---

## CSLB Master License Data (`intake/cslb_ca.py`, source `cslb-ca`)

**File:** `MasterLicenseData.csv` — CSLB public licensee export, statewide CA.
**Profiled:** 243,271 rows, 2026-07-11 snapshot.

| Fact | Value |
|---|---|
| Phone coverage | **100%** (243,023 / 243,271 have `BusinessPhone`) |
| Trade | Authoritative — `Classifications(s)` license codes (C36 plumbing, C10 electrical, C20 HVAC, C33 painting, C27 landscaping, C39 roofing, B general…) |
| License status | `PrimaryStatus`: CLEAR 232,898 (96%); rest are suspensions (bond / WC / SOS / liability) — exclude by default |
| Structure | `BusinessType`: Sole Owner 115,906 · Corporation 110,284 · LLC 12,933 |
| Solo signal | `WorkersCompCoverageType = 'Exempt'` = licensee legally declared **no employees** — 119,338 (49%) |
| Geography | `County` populated (LA 49,546 · San Diego 21,545 · Orange 20,114) |
| Maturity | `IssueDate` (license age); `ExpirationDate` 2-year renewal cycle |

### ⚠️ Trap: WC-Exempt is NOT a valid solo proxy for every trade — and it expires

California requires workers'-comp coverage **regardless of employees** for some
classifications, so licensees in those classes are almost never `Exempt` no matter how solo
they are:

- **C-39 roofing** — long-standing pre-SB-216 law. Observed: **0** exempt of 1,158 LA roofers.
- **C-8 concrete, C-20 HVAC, C-22 asbestos, D-49 tree service** — SB 216 Phase 1, since
  2023-01-01. Observed: **7** exempt of 2,846 LA HVAC.

**Use WC-Exempt as a solo filter only for classes outside that set** (C36 plumbing, C10
electrical, C33 painting, C27 landscaping, B, …).

**Decay:** SB 216 Phase 2 extends the mandate to **all** classifications. Originally
2026-01-01, **delayed by SB 1455 to 2028-01-01**, with CSLB exemption re-verification during
2027. So the Exempt flag is usable through ~2027 and **meaningless from 2028** (and will
thin out during 2027 as re-verification processes). Re-check this section before trusting
the filter on any post-2026 snapshot.
*Verified 2026-07-11: [SB-216 text](https://leginfo.legislature.ca.gov/faces/billNavClient.xhtml?bill_id=202120220SB216),
[State Fund](https://www.statefundca.com/state-fund-today/what-you-need-to-know-about-sb-216/),
[CCIS on the SB 1455 delay](https://www.ccisbonds.com/blog/do-californias-new-bills-require-workers-comp-coverage-for-contractors-understanding-2026-requirement-changes/).*

### Other notes

- Multi-class licenses are common (a plumber may also hold B). The adapter assigns one
  primary trade by a fixed priority; the full class string rides in `license_class`.
- ICP slice sizes (CLEAR, LA County, 2026-07-11): plumber 4,568 (solo 2,392) ·
  electrician 6,653 (3,457) · HVAC 2,846 (solo n/a per trap) · painter 2,851 (1,470) ·
  landscaper 1,629 (633) · roofer 1,158 (solo n/a).

---

## LA County FBN filings (`intake/fbn_ca.py`, source `fbn-ca-<year>`)

**File:** `Fictitious_Business_Name.csv` — LA County Registrar-Recorder DBA filings.
**Profiled:** 236,894 rows (2024–2026), 2026-07-11.

| Fact | Value |
|---|---|
| Scope | **LA County only** — despite early assumption of statewide/US. Out-of-state rows are non-resident owners filing in LA |
| Phone | **0%** — dataset has no phone column. Attribution is mailer-code-only for this list |
| Trade | Absent. ~13% of business names carry a service-trade keyword (heuristic only) |
| Live vs dead | `FilingType`: only `FBN Statement` is a live prospect; Amendments/Renewals re-describe the same business; **Abandonments/Withdrawals are closures — never mail** |
| Structure | `BusinessType`: Individual 51% · Corp/LLC 45% (entity = commitment signal) |
| Solo tell | ~12% of names ≈ owner's own name (2+ shared tokens) — likely one-person operations |
| Address quality | 0% missing street; 75 PO Box/PMB; **211 contacts at addresses hosting ≥5 businesses** (mailbox stores / registered agents — exclude) |
| Residential vs business | Not in the data. Heuristics: apt/unit markers 22%, suite/floor 13%. Authoritative answer = USPS **RDI** flag from Lob address verification (the deferred NCOA/CASS intake job) |

**2026 mailable slice** (statements only, deduped): 18,359. Service-trade-name + clean
address: 1,828 (Corp/LLC subset: 666).

---

## Cross-list rules

- Every list flows through its own adapter in `intake/` to the canonical CSV; the spine
  never learns vendor columns (PRD FR-1).
- `list_key` prefixes keep lists collision-free: `cslb-<LicenseNo>`, `fbn-ca-<FilingNumber>`.
- A licensee can appear in both lists (contractor who filed a DBA). Cross-list dedupe is
  NOT automatic — `list_key` spaces are disjoint. If both lists load, expect some double
  mailing across sources until a phone/address-level dedupe exists.
