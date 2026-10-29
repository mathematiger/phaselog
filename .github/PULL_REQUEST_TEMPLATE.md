<!-- Thanks for the change. CONTRIBUTING.md has the reasoning behind the checklist below; this is the short form. -->

## What this changes, and why it was wrong before

<!-- One or two paragraphs. For a fix, the interesting half is the second one: what did the old code report, and what would a reader have concluded from it? -->

## Evidence

<!-- Delete what does not apply. -->

- **Failing test first:** <!-- name the test, and confirm you watched it fail before the fix existed -->
- **Rendered output:** <!-- if this can reach a report, source view or timeline: paste the relevant block of a page generated from a real run, not a fixture -->
- **Hot path:** <!-- if this touches `_PhaseScope`, the trace buffer or the histogram: before/after from `benchmarks/bench_accounting.py` -->

## Checks

- [ ] `poetry run ruff check phaselog tests`
- [ ] `poetry run mypy phaselog tests`
- [ ] `poetry run pytest tests/`
- [ ] I generated the affected page from a real run and read it end to end
- [ ] `CHANGELOG.md` entry added
- [ ] `HARDENING.md` row added (wrong-numbers fixes only)
- [ ] Docs under `docs/` updated (public API changes only)
- [ ] No new entry in `[project.dependencies]`
