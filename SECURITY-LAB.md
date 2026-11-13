# Security lab: intentional vulnerabilities

> **This app is intentionally vulnerable.** It is a remediation target for the
> [CodeMender + Wiz MCP lab](https://github.com/avnit/codemender-mcp/tree/split-codemender-wiz-mcp/lab).
> Deploy it only to a throwaway lab project and delete it afterwards.

The layout mirrors the lab's `sample-app/` (`payment-service`), so the lab's
sandbox, workflows and exercises work on this app with the same issue IDs.

## Findings

| ID | Weakness | Where | Reachable from | Reference fix |
|---|---|---|---|---|
| CM-0001 | CWE-89 SQL injection | `app/db.py` `search_items()` | `GET /api/items?source=` | `patches/CM-0001-sqli.diff` |
| CM-0002 | CWE-22 path traversal | `app/notes.py` `read_note()` | `GET /api/notes?file=` | `patches/CM-0002-path-traversal.diff` |
| CM-0003 | CWE-312 DB root password as a plaintext env value (and CWE-250: app connects as `root`) | `terraform/main.tf` | Cloud Run revision config, Terraform state | Secret Manager + `value_source.secret_key_ref`, least-privilege DB user |
| CM-0004 | CWE-1104 end-of-life base image | `Dockerfile` (`python:3.8-slim-buster`) | Container image | `python:3.12-slim-bookworm` or newer |

CM-0001 and CM-0002 have a PoC test and a reference patch, so they run through
the lab's validation sandbox end to end. CM-0003 and CM-0004 are configuration
findings for the Wiz / investigation exercises; fix them by hand or with the agent.

Every vulnerable line is marked with a `VULNERABLE (CWE-…)` comment.
`.codemender/mock-findings.json` holds the same four findings for the lab's
`codemender-scan.yml` mock mode.

## Try the exploits

```bash
curl -G "$URL/api/items" --data-urlencode "source=' OR '1'='1"   # CM-0001: every item, not one source
curl "$URL/api/notes?file=../not_a_secret.txt"                   # CM-0002: a file outside data/notes/
```

## Tests and the sandbox contract

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests/unit   # legitimate behaviour: must always pass
python -m pytest -q tests/poc    # PoCs: PASS while the app is still exploitable
```

- A PoC in `tests/poc/test_poc_*.py` **passes when the exploit works** — the
  lab's convention. Sandbox verdict `PATCH_VERIFIED` means: PoC passed before
  the patch, failed after it, and `tests/unit` still passed.
- Tests force the SQLite backend, so they run in the sandbox (no egress, no
  MySQL) using only the `flask` and `pytest` already baked into its image.
- `app/db.py` runs the same SQL on SQLite and MySQL: write `?` placeholders and
  `_run()` converts them for MySQL. A fix proven in the sandbox is therefore the
  same fix that runs against MySQL on Cloud Run.

Check a patch by hand:

```bash
git apply patches/CM-0001-sqli.diff
python -m pytest -q tests/poc/test_poc_sqli.py   # now FAILS = exploit blocked
python -m pytest -q tests/unit                    # still passes
git apply -R patches/CM-0001-sqli.diff            # restore the vulnerable code
```

## Using it with the lab

The lab expects the vulnerable app at the **root of its own GitHub repo**
(`app/`, `tests/`, `Dockerfile`, `patches/` at top level), which is how this
repo is laid out. To use it:

1. Copy `.github/workflows/codemender-scan.yml`, `sandbox-validate.yml`,
   `CODEOWNERS` and the PR template from the lab's `sample-app/.github/`.
2. If you fork this repo, update `repository` in `.codemender/mock-findings.json`.
3. Wherever the lab says `payment-service`, use this repo and the Cloud Run
   service `watchlist`; `app/receipts.py` in the lab corresponds to
   `app/notes.py` here, and `/api/transactions?account=` to `/api/items?source=`.
4. In Module 08, run the remediation exercise as written:
   `Remediate CM-0001 (wiz-issue-0001). Start with root cause.`

## Reset between sessions

Revert merged fixes (or re-push this folder) so the vulnerabilities exist
again, and delete participant branches and PRs.
