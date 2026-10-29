# Contributing to phaselog

Thanks for looking. This is a small project with a specific obsession, and the fastest way to get a change merged is to know what that obsession is.

## What this project is afraid of

Not crashing. **Reporting a number that is wrong and looks right.** A profiler that dies is annoying for an afternoon; a profiler that confidently attributes 0.2 ms to a call that took half a second sends someone optimising the wrong function for a week, and they never find out. Most of the rules below exist because that happened.

So the bar for a change is not "the tests pass". It is: *can this make a reader believe something untrue?* Concretely:

- **Never let "unmeasured" be representable by a valid value.** `-1` means not measured; `0` means measured as zero, and an idle process legitimately reports zero. Anything differenced needs an `available` flag beside it.
- **A measured number is never truncated; a derived one may be compacted.** An overflowing count pushes its row right rather than printing a wrong value. Truncating a label loses nothing — the full name is in the JSON payload. Truncating a measurement invents one.
- **An estimate must stay labelled everywhere it is rendered.** Sampled phases carry `sample_stride`; every renderer that shows them must say so and name the rate.
- **A caveat sits with the number it qualifies**, not only in a trailing block eighty lines below.

## Reporting a bug

Use the issue forms. The **wrong numbers** form exists because that report needs different evidence from a crash report — the artifacts (`report.txt`, the run directory, the HTML page) and, most importantly, *what you expected the number to be and why*. A traceback is optional there; an expectation is not.

If you are not sure whether something is a bug or a limitation, [HARDENING.md](HARDENING.md) is the ledger of everything that has been probed, including rows marked *not-a-bug* with the reasoning. It is worth searching before filing.

## Setting up

The repo root is the directory containing `pyproject.toml`.

```
poetry install --extras resources
```

Install the `resources` extra even if you do not care about it: without `psutil` the I/O and memory paths silently degrade to their absent-capability branches and stop being tested. `poetry install --extras all` plus `torch` is needed only to run the GPU tests, which skip cleanly otherwise.

## The four checks

Run all four before opening a pull request. CI runs the first three on 3.10–3.13; the fourth is on you.

```
poetry run ruff check phaselog tests
poetry run mypy phaselog tests
poetry run pytest tests/
```

4. **Render the page and read it as a human.** Any change that can reach a report, a source view or a trace timeline ends by generating that artifact *from a real run, not a fixture* and reading it end to end as someone who did not write it. A passing suite says the page is well-formed; it does not say the page is readable, and the whole output of this project is something a person opens and has to understand. Does it answer the question it was opened with? Is every figure labelled with what it excludes? Does anything overflow or run together? Then fix what the read turned up and render again.

`pytest -m overhead` runs the hot-path cost assertions. They are sensitive to machine load and are a separate CI job for that reason; run them locally on an idle machine or not at all.

## Making a change

**Start with a failing test.** For a bug, write the test that reproduces it and watch it fail before you write the fix — a test written after the fix proves the fix exists, not that it was needed. Several tests deliberately build traces by hand rather than profiling: a finding about "the lane idle 80% of the run" needs a run idle exactly 80%, which a real workload cannot promise.

**Keep the change surgical.** Touch only what the change requires. Don't reformat adjacent code, don't refactor what is not broken, and match the surrounding style even where you would do it differently. If you notice unrelated dead code, mention it in the pull request rather than deleting it.

**Zero required dependencies is a feature, not an accident.** Nothing may be added to `[project.dependencies]` (`tomli` on 3.10 is the sole exception, and it disappears above 3.10). Optional integrations go through `capabilities.py`, are imported lazily, and degrade to `None` — a missing one disables one block of the report instead of raising.

**The HTML output stays self-contained.** Inline CSS, hand-built SVG, no CDN, no webfont, no network of any kind. The report and source pages ship no script at all; the trace timeline is the single deliberate exception and its script writes text with `textContent`, never `innerHTML` — a phase name reaching `innerHTML` is XSS in a file people email to each other. There are tests for all of this.

**Every user-supplied label goes through a bounding chokepoint**: `report.format_label` for text, `htmldoc.clip_label` plus `htmldoc.escape` for HTML. A new column or page that formats a phase name without one reopens both the width and the control-character defects.

**Mind the hot path.** `_PhaseScope.__exit__` costs about 3 µs and is the product. A Python-level method call there is measurable, which is why `record()` and `observe()` are inlined at the call site — a new field must be written *there* as well as in `record()`, or it stays zero in real runs while unit tests calling `record()` pass. Run `poetry run python benchmarks/bench_accounting.py` before and after anything that touches it.

**Markdown is one paragraph per line.** Never hard-wrap prose in `.md` files, however long the line. GitHub and VS Code reflow to the pane width; a manual break becomes a forced mid-sentence break in the rendered output. Code blocks and table rows keep their exact line breaks.

## Reliability work

Hardening runs as an explicit loop, and [HARDENING.md](HARDENING.md) is its ledger: one row per iteration, recording the surface probed, what was found, the fix, and the test. **Read it before probing anything** — rows marked *fixed*, *clean* or *not-a-bug* carry their reasoning, and they are what stop the loop cycling over the same ground. A pull request that fixes a wrong-numbers defect should add its row.

## Housekeeping

- The version lives in **two** places that must be bumped together: `[project].version` in `pyproject.toml` and `__version__` in `phaselog/__init__.py`.
- Regenerate the report golden files with `PHASELOG_UPDATE_GOLDEN=1 poetry run pytest tests/test_accounting_report_golden.py`, and read the resulting diff — that file is a rendered page, and a golden update is where a readability regression sneaks in unnoticed.
- Add a `CHANGELOG.md` entry saying what changed *and why it was wrong before*. The changelog here is written for someone deciding whether their old numbers were trustworthy.
- Public API changes need the docs under `docs/` updated in the same pull request.

## Licence

By contributing you agree that your contribution is licensed under the MIT licence, the same as the rest of the project.
