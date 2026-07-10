# Direct Mail AI — Judgment Job

*The nightly evaluation that turns contact state into founder action. This is the component that replaces the CRM: nobody checks a pipeline; the system taps the right founder on the shoulder. Companion to the data and service contract documents.*

---

## 1. Architecture: rules detect, AI composes

The job is two-tier, and the tier boundary is the design's load-bearing wall.

**Tier 1 — deterministic rules decide WHO and WHEN.** Conditions are SQL against contact state and the event stream: quiet-too-long, activation stalled, mail returned. Rules are cheap, auditable, and testable — you can always answer "why did I get this nudge?" with a rule name and the rows that matched. No LLM decides *whether* a nudge fires.

**Tier 2 — AI composes WHAT.** For each firing, the model receives the contact's full event timeline and writes the nudge: a two-sentence brief with the context a founder needs to act in thirty seconds — who, what happened, what they said last, suggested move. The AI is a briefing officer, not a decision-maker. If composition fails, the nudge still sends with a plain template; delivery never depends on the model.

Why this split: LLM-as-detector fails quietly (a missed condition leaves no trace) and drifts with model changes; rules-as-composer produces briefs nobody reads ("Contact 4471 status changed"). Each tier does what it's reliable at.

---

## 2. The rule catalog (initial set)

Each rule: condition → recipient → action slot. All thresholds are parameters (§4), not constants.

| Rule | Condition | Recipient | Nudge intent |
|---|---|---|---|
| `quiet_reengage` | stage `in_conversation`, last inbound > QUIET_DAYS, no human-set next_action | Deal owner | "Ping today" with thread summary |
| `hot_response` | new `responded` since last run (first inbound from a contact) | Deal owner | "New responder — reply while warm" (this one also fires morning-of, not just nightly, if volume justifies later) |
| `demo_no_show` | `demo.booked` passed, no `demo.held`, no rebook | Deal owner | "No-show yesterday — one graceful rebook text" |
| `activation_stalled` | `signed_up_at` > STALL_DAYS, `first_lead_at` null | Young | "Customer never activated — churn risk, call them" |
| `activation_partial` | forwarding or calendar step null > PARTIAL_DAYS after signup | Young | "Stuck at setup step X — offer to walk them through" |
| `returned_mail` | 2nd `piece.returned` for a contact | Young | Auto-suppressed; FYI roll-up, not per-contact |
| `wave_anomaly` | delivery failure rate for an executing wave > FAIL_PCT, or zero responses by day RESP_CHECK_DAYS | Young | "Wave 3 looks broken/dead — investigate before drop 2 fires" |
| `approval_pending` | wave `scheduled_for` within LEAD_DAYS, status still `draft` | Young | "Wave needs your approval or it slips" |
| `orphan_events` | unmatched events > ORPHAN_MAX, weekly | Young | Weekly roll-up: attribution leaks to review |
| `lost_aging` | stage `responded`/`in_conversation`, no inbound > AGE_OUT_DAYS despite nudged pings | Deal owner | "Propose marking lost — or one last postcard-style text" |

Deal owner = whichever founder owns the contact (Young for mail-channel, partner for affiliate referrals — one `owner` column on contacts, defaulted by source).

---

## 3. Nudge discipline (what keeps this from becoming noise)

The failure mode of every notification system is the same: it cries wolf, gets muted, and dies. These rules exist to keep the channel trusted.

- **Daily budget.** Max NUDGE_BUDGET per founder per day (start: 5). Overflow is ranked and deferred, not dropped — priority order: hot_response > activation_stalled > demo_no_show > quiet_reengage > everything else. A morning with 12 nudges means the budget is teaching you something about capacity, not that the budget is wrong.
- **Cooldown per contact.** Once nudged about a contact, that contact is quiet for COOLDOWN_DAYS (start: 3) unless a *new inbound event* changes the situation. The system never nags twice about the same silence.
- **Expiry, not escalation.** A nudge unacted-on for EXPIRE_DAYS (start: 5) expires and the rule re-evaluates fresh. No guilt-stack of stale nudges; the morning list is always current-state truth.
- **One digest, not a drip.** All nudges land as one morning SMS/email per founder (dogfooded through NMC's own sending infra), ordered by priority. Exception: `hot_response` may send same-day — a warm responder is the one case where hours matter.
- **Silence is a valid output.** A morning with zero nudges sends nothing. No "all clear!" messages; an empty channel stays a trusted channel.

---

## 4. Parameters (config table, not code)

| Param | Start | Rationale |
|---|---|---|
| QUIET_DAYS | 4 | Contractor rhythm: under a sink for days is normal; a week is drift |
| STALL_DAYS | 14 | Two weeks without first captured lead = churn cliff |
| PARTIAL_DAYS | 4 | Setup friction shows fast |
| FAIL_PCT | 8% | Above list-decay baseline for validated addresses |
| RESP_CHECK_DAYS | 10 | Mail response tail; zero by day 10 is signal |
| LEAD_DAYS | 3 | Print API needs runway |
| AGE_OUT_DAYS | 30 | Simple product; a month of silence after pings is an answer |
| NUDGE_BUDGET | 5/day | Founder attention is the scarce resource |
| COOLDOWN_DAYS | 3 | Never nag twice about the same silence |
| EXPIRE_DAYS | 5 | Morning list = current truth |

All tunable in one config table; changes are events (`system` source) so parameter history is auditable alongside outcomes.

---

## 5. The loop closes: nudges are events too

Every nudge emitted is written to `events` (`source='system'`, `type='nudge.sent'`, payload = rule, contact, brief). Founder actions after a nudge are already captured by existing inflows (outbound SMS, notes, outcome verbs). This makes the judgment job itself measurable:

- Which rules produce action, and which get ignored?
- Do `quiet_reengage` pings actually revive conversations, or is QUIET_DAYS wrong?
- Is the budget ever binding, and what gets deferred?

Monthly, the same conversational analysis surface that reads wave results reads nudge results — and proposes parameter changes for approval. The judgment job is subject to the same information-buying posture as the postcards: every rule is a hypothesis about what deserves founder attention, and the event stream grades it.

---

## 6. Mechanics

Runs nightly after the sync jobs and `recompute_state` complete (order matters: judge fresh state only). Sequence: evaluate rules → write `next_action_at`/`next_action_note` for rule hits (never overwriting an unexpired human-set action) → rank against budget → compose briefs (AI, template fallback) → emit one digest per founder → log everything as events. One transaction per contact touched; a composition failure never blocks the digest.

Total new surface: one job, one config table, one `owner` column on contacts. Everything else it needs already exists.
