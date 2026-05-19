# AGENTS.md

This file defines practical operating guidelines for humans and AI agents working in this repository.
Optimize for consistent quality, small safe changes, and reproducible results.

## Core Principles

1. Prefer clarity over cleverness.
2. Make the smallest change that fully solves the problem.
3. Preserve existing behavior unless a behavior change is explicitly requested.
4. Verify with tests or concrete checks before concluding work.
5. Create enough tests to cover relevant code paths before refactoring and ensure they pass before changes.
6. Document intent when code is not immediately obvious.

## Shell usage
Do not use Get-Content to read code files this triggers a bug in IntelliJ.

## Recommended Delivery Workflow

1. Understand the request and constraints.
2. Inspect current code paths before editing.
3. State assumptions when requirements are ambiguous.
4. Implement minimal, focused changes.
5. Run targeted validation first, then broader checks as needed.
6. Summarize what changed, why, and how it was verified.

## Definition of Done

A task is done when:

1. Requested behavior is implemented.
2. Relevant tests/checks pass (or failures are explained).
3. Risks, assumptions, and limitations are explicitly noted.
4. The change is understandable by someone new to the code.





