# Release checklist

Use this before publishing a release. Every box is a command or a decision, not a
feeling. Nothing on this list publishes anything by itself.

## 1. Tests and evidence

- [ ] `python tests/test_acceptance.py` → 10/10
- [ ] `python tests/test_migration.py` → 7/7
- [ ] `python tests/test_memory_architecture.py` → 8/8
- [ ] `python tests/test_mcp_schema.py` → 11/11
- [ ] `python tests/test_security.py` → 14/14
- [ ] `python demo/demo.py --check` → "transcript matches expected_output.txt"
- [ ] `python demo/demo.py --tmp --check` → same (proves it runs against a temp DB)
- [ ] `python eval/harness.py` → completes and rewrites `eval/results.json` +
      `eval/REPORT.md`; the numbers in `docs/TECHNICAL_REPORT.md` still match
- [ ] `python mcp_server.py --print-schemas` → six tools, `export` absent

## 2. Superseded or unverified statements

- [ ] Every number quoted in `README.md`, `docs/TECHNICAL_REPORT.md` and `eval/REPORT.md`
      still matches the current `eval/results.json`
- [ ] No document claims a client (Grok CLI, Claude Code, Cursor, Hermes MCP) was tested
      against `mcp_server.py` unless a session actually was — the current docs say it was
      not
- [ ] No document claims encryption, tamper-evidence, capability-based security,
      multi-tenancy, "unhackable", "conscious", "self-learning" or "enterprise-ready"
- [ ] `docs/PHASE_STATUS.md` "not done" entries are still accurate

## 3. Repository hygiene

- [ ] `git status` is clean; no database, `.bak`, log or export file is tracked
- [ ] `git ls-files | grep -Ei '\.(db|sqlite|bak|key|pem)$|_export\.json'` → no matches
- [ ] No real memory content, credential or personal data appears in any file, commit
      message or test fixture (`python tests/test_security.py` scans tracked files for
      credential shapes)
- [ ] `demo/.demo_db/`, `hungry_hippa.db*` and `living_cortex.db*` are still ignored
- [ ] The changelog entry for this release exists and matches the diff

## 4. Version and metadata

- [ ] `version:` in `plugin.yaml` bumped if behaviour changed
- [ ] `CHANGELOG.md` has an entry for the new version with the date
- [ ] `plugin.yaml` `description` still names Hungry Hippa and keeps `living-cortex` as
      the plugin `name`
- [ ] `LICENSE` copyright line is current

## 5. Compatibility

- [ ] `python -m pip install -e .` succeeds on a clean interpreter and
      `python -c "import mcp"` reports the SDK version
- [ ] The `cortex` tool still exposes every previously supported action
      (`record_outcome` and `explain` are additive)
- [ ] `hungry-hippa migrate --db <copy>` still backs up and migrates a copy of a
      pre-v4 database, and the migration test covers it
- [ ] Table names and existing row ids are unchanged

## 6. Documentation

- [ ] `README.md` opens with the exact required sentence and its quick-start commands
      work as written (copy the commands out and run them)
- [ ] All relative links in `README.md`, `docs/*.md`, `CONTRIBUTING.md`, `SECURITY.md`,
      `CHANGELOG.md` resolve to existing files
- [ ] The mermaid diagram in `README.md` names only modules that exist
- [ ] `docs/MCP.md` still marks client snippets as untested
- [ ] `SECURITY.md` disclosure routes (GitHub advisories/issues) are correct and no
      invented email address is present

## 7. Continuous integration

- [ ] `.github/workflows/test.yml` runs every test file plus the demo check
- [ ] CI has actually run green on the release commit. Python 3.12/3.13 passed on
      `main` at `905167d` ([run 34932877707](https://github.com/TRUE-BLUE-INDUSTRIES/hungry-hippa/actions/runs/34932877707)).
      Check the selected release commit again; see [follow-up](FOLLOWUP.md).

## 8. Publishing

Status: the repository is public and both `feat/hungry-hippa` and `main` are pushed, with
CI green on every pushed commit. The steps below remain the checklist for a *release*
(a tag or announcement), which has not been done; publishing anything further still needs
the operator's explicit approval.

- [ ] Decide the release channel and version tag with the operator
- [ ] Get explicit approval for the release (pushing an ordinary commit is not a release)
- [ ] Tag or open the PR, and let CI run on it
- [ ] After publishing: confirm no secrets and no personal memory data are in the public
      history (`git log --all --stat`), and that the README's claims still hold on the
      published commit

## Rollback

- Code: revert the release commit (`git revert <sha>`), or check out the previous tag.
- Database: restore the `*.pre-hippa-<UTC>.bak` file written by
  `hungry-hippa migrate`, then optionally set `LIVING_CORTEX_DB` back to the old
  path. See `docs/MIGRATION.md`.
