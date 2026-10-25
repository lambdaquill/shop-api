# shop-api + doc-agent

A small Flask API that demonstrates a **self-updating documentation pipeline**
(Google ADK + GitHub Actions). Change any code, push, and `docs/DOCUMENTATION.md` is updated
automatically, including **architecture diagram, request-flow diagrams, API table, file tree,
modules, dependencies, env vars and tests**.

There is intentionally no `docs/` folder yet. The first run creates it.

## How it works
Two layers, so facts are always right and prose stays natural:

| Layer | Who writes it | When | Sections |
|---|---|---|---|
| `<!-- AUTO:* -->` | Python analyzer (AST), **no LLM** | every push | At a Glance, Architecture diagram, Request Flows (sequence diagrams), Project Structure, API Reference, Modules, Dependencies, Configuration, Tests, (Recent Changes) |
| `<!-- NARRATIVE:* -->` | Gemini via ADK agent | first run, or when the git diff matters | Overview, Architecture notes, Setup & Usage |

Anything outside those blocks is yours and is never touched.

    push -> workflow -> run_agent.py
              1. refresh AUTO blocks from code (deterministic, free)
              2. no relevant diff?  -> stop (no LLM call)
              3. else agent reads `git diff`, rewrites only affected narrative sections
              4. optional pandoc -> PDF/DOCX/HTML
              5. bot commits docs/ (commit skipped if nothing changed)

## Quick start (local)
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt -r requirements-docs.txt
    export GOOGLE_API_KEY="your_key"          # optional for AUTO sections, required for narrative
    git init && git add -A && git commit -m "initial"
    python run_agent.py
    open docs/DOCUMENTATION.md                 # diagrams render on GitHub / VS Code (Mermaid)

Run the app and tests: `python app.py` and `pytest`.

## Try changes (each should show up in the doc)
| Change | Doc effect |
|---|---|
| Add a route in `routes/orders.py` | API table, architecture diagram, request flows |
| Add `services/notifications.py` and call it from a route | new box + arrow in diagram, new participant in flow, modules table, structure tree |
| Add `os.getenv("SMTP_HOST", "localhost")` | Configuration table |
| Add a package to `requirements.txt` | Dependencies table |
| Rename/delete a file | tree, modules, diagram updated; stale references vanish |
| Fix a typo / comment | **no doc change, no commit** |

Always `git commit` between changes, because the agent diffs against the previous commit.

## GitHub setup
1. Push this repo to GitHub (default branch `main`).
2. Settings > Secrets and variables > Actions > **Secret** `GOOGLE_API_KEY`.
3. Optional **Variables**: `DOC_FORMATS` = `pdf,docx` (needs pandoc, installed automatically), `DOC_CHANGELOG` = `true`.
4. Settings > Actions > General > Workflow permissions: **Read and write**.
5. Push a change and watch the **Actions** tab.

## Config (env vars)
`DOC_PATH` (default `docs/DOCUMENTATION.md`), `DOC_MODEL` (default `gemini-2.5-flash`), `DOC_FORMATS`,
`DOC_CHANGELOG`, `DOC_EXCLUDE` (default `doc_agent/,run_agent.py`: paths hidden from the docs), `MAX_DIFF_CHARS`, `BASE_SHA`.

## Limits (honest)
- Deep analysis (endpoints, call flows, modules, env vars) is for **Python** (Flask/FastAPI-style decorators). JS/TS gets basic Express route detection. Other languages get the file tree, dependencies and AI narrative only.
- Call-flow diagrams follow calls between your own modules up to 2 levels deep and use the names imported in the file.
- PDF/DOCX show Mermaid diagrams as code blocks. Diagrams render natively in Markdown on GitHub/VS Code.
- If `main` is branch-protected, replace the last workflow step with `peter-evans/create-pull-request`.
