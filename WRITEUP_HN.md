# I built an agent that opens PRs on dead repos. It learned to refuse.

*April 2026. 10 days of working in public on an autonomous agent for dead GitHub repositories.*

---

## The problem nobody talks about

There are millions of inactive Python repositories on GitHub. Many of them still work — but slowly, silently, they're breaking. A pinned dependency releases a security patch that drops Python 2 support. A new pip version refuses to install packages without a `python_requires` declaration. An `imp` module that worked in Python 3.8 disappears in 3.12.

The maintainer moved on years ago. Nobody's watching. The repo just... sits there, gradually becoming incompatible with the world around it.

I wanted to build something that would actually help: an autonomous agent that could find these repos, understand what they needed, and open a polite modernization PR — without annoying the maintainer.

That was the plan. The plan changed.

---

## The naive version

Here's what the first version did: find a repo, bump the dependencies, open a PR.

Sounds reasonable. Here's what actually happened on the first real target — a small terminal game called term2048, maintained by a developer who'd closed their GitHub account:

```
🤖 This pull request was opened by repo-revival-agent
```

One line. The agent bumped some pinned versions and opened a PR. A few days later, the (former) maintainer closed it with two complaints: the changes hadn't been tested, and the PR was opened from a personal account with no LLM-authorship disclosure.

Two distinct, valid complaints. Both my fault.

**First problem:** the agent had never actually run the test suite. It bumped dependencies and opened a PR without ever validating that the changes worked. The PR body had a "what was NOT tested" section — honest, but useless. A maintainer can't merge changes that the author didn't test.

**Second problem:** the agent was opening PRs under a personal GitHub account, with no disclosure that the content was LLM-generated. That looks like a person spamming maintainers.

I closed the PR. Started over.

---

## The honest design

The second version had three hard rules:

**1. Tests must pass before any PR opens.** Not advisory — the pipeline aborts and does nothing if the test suite fails or is missing.

**2. Every PR and issue gets a visible LLM-authorship header.** Not optional, not configurable. It's prepended programmatically after the LLM generates the body, so the model can't skip it.

**3. The agent uses its own GitHub account.** Not my personal account. A dedicated bot identity (`@repo-revival-agent`) with a public profile that explains what it does and how to opt out. The source code repo lives on my personal account; only the agent's runtime actions — forks, PRs, issues, comments — happen from the bot.

That's the foundation. Everything else is execution.

---

## The pre-baseline check

When I added the test runner, I expected a simple gate: run tests → pass or fail → open or abort.

But the repos I'm targeting are often already broken. Some have pre-existing test failures. Some have collection errors from Python 2 syntax that was never cleaned up. If the baseline (pre-change) test run already fails, a post-change failure doesn't mean *we* broke anything.

So the agent now runs tests **twice**: once before any changes (baseline), once after. Then it compares the signatures — which specific files and exception types failed — rather than just looking at pass/fail counts.

This matters more than it sounds. Here's why:

The term2048 repo had 4 collection errors before any changes. Our codemod fixed one of them (replacing a deprecated `imp.reload` with `importlib.reload`). That left 3 errors — but they were **different** errors in different files. A naive comparison would say "4→3 errors, improvement!" and open a PR. The signature comparison correctly identifies this as "2 new failures introduced, 1 fixed, 1 pre-existing" — a regression, not an improvement.

The agent correctly refused to open a PR.

---

## The interesting part

For pycycle (a dependency cycle detection tool), the baseline and post-bump runs were identical: same test failing before, same test failing after. Verdict: `no_regression`. Pre-existing failure labeled honestly.

For term2048, verdict was `regression`. The agent tried to fix the remaining errors with an LLM-guided edit — and made it worse. The LLM wrapped the failing line in a `try/except` instead of understanding why pytest was capturing stdin during collection. The error count went from 3 to 1... but the one remaining error was a new `AttributeError`, not the original `io.UnsupportedOperation`. Errors increased by severity, even if they decreased by count.

The agent caught this: it compared before/after signatures, detected the regression, rolled back the change, and aborted. No PR opened.

This is the part of the system I'm proudest of: **the most useful thing the agent did was refuse**. It's the right thing to design for, even if it makes the demo less flashy.

---

## The compliance-fix problem

The LLM tendency to wrap rather than understand is worth naming. The model sees a test failure and reaches for "add error handling around the failing call." It's the coding equivalent of turning down a hard conversation — suppress the symptom, avoid the cause.

We got lucky: the rollback mechanism caught the compliance fix before it shipped. But the mechanism shouldn't be necessary. The real fix is to improve the LLM's instruction set — make it prefer "understand the root cause" over "wrap the failing line" — and make the rollback unnecessary.

This is a known limitation. It's on the list.

---

## What this is NOT

This is not a "we revived 50 dead repos" story. We tested on two repos. One was correct to open a PR on; the other was correct to refuse.

This is not a commercial product. There's no SaaS, no waitlist, no "sign up to get your repo fixed." The code is on GitHub under an MIT license. If you want to run it against your own repos, you can.

This is not a showcase for any particular AI model. The agent runs on Claude Opus 4.7. The interesting design choices — the test gate, the baseline comparison, the refusal to open uncertain PRs — are architectural, not vendor-specific.

---

## Code and context

- Repo: github.com/Selliksss/repo-revival-agent
- License: MIT
- Stack: Python 3.12, Claude Opus 4.7, gh CLI, pytest

No product claims. No "disrupting open source." Just an agent that learned when not to act.

Sometimes the right answer is to do nothing.

---

*Build log with full technical details: `BUILD_LOG.md`*