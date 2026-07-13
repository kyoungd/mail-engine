# creative/ — postcard authoring workspace

These files are **sources for authoring, not runtime**. What actually prints is the
`creative` JSON stored on a variant row in the database — created once via the
Variants page (or `create_variant`) and immutable after that. Approval renders
exactly what the DB holds; nothing here is read by the app.

## Workflow

1. Edit `front.html` / `back.html` in a variant folder (copy a folder for a new
   variant; git tracks the design history).
2. When ready, create the DB variant from these files — Variants page at
   `/variants`: name + hypothesis (required) + the creative JSON
   `{"front": "<file contents>", "back": "<file contents>", "size": "...",
   "mail_type": "..."}` per `variant.json`.
3. Submit a test drop on the Lob **test** key and judge the rendered PDF proof in
   the Lob dashboard (Test environment → Postcards). Redline here, repeat.
4. A DB variant is create-only. To revise a design, edit here and mint a NEW
   variant — the old one stays as the audit trail of what actually mailed.

## Rules every card must follow

- **`{{mailer_code}}` must appear in the tracking URL** — it is the entire
  attribution chain: `getnevermisscall.com/?r={{mailer_code}}` (note: the
  **getnevermisscall.com** domain — the main product site does not capture `?r=`).
- Campaign phone line: **(888) 866-9044** (SMS-first sales AI).
- 4×6 full-bleed: body sized **6.25in × 4.25in** (0.125in bleed per edge); keep
  text inside ~0.4in padding. Lob reserves the address/IMb zone on the back —
  the proof render shows what survives.
- Recipient name/address and the return address are injected by the system
  (`seams/lob.py`) — never put addresses in the creative.
- Keep the variant's one-line hypothesis honest: the wave readout grades the
  copy against it.
