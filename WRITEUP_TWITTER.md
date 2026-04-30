# Twitter thread — repo-revival-agent

---

**Tweet 1** (hook)

the most useful thing my AI agent did this week was refuse to open a PR.

not "refused because it crashed" — refused because it ran the tests, checked the signatures, and correctly concluded it would make things worse.

---

**Tweet 2** (what the agent is)

I built an agent that finds dead Python repos and opens modernization PRs. The naive version: bump deps, open PR. That broke things.

The honest version: run the test suite, check if *we* caused the failures, refuse if we did.

---

**Tweet 3** (maintainer feedback)

A maintainer replied to the first PR my agent opened (term2048):

"if you don't test your changes I can't accept them. also run this under its own account."

I closed the PR. Built the test gate properly. Started over.

---

**Tweet 4** (the pre-baseline insight)

The agent runs tests twice: baseline (before changes) and current (after). Then compares failure signatures — files + exception types — not just counts.

Why: 4→3 errors looks like improvement. But if the 3 are different files, you introduced 2 new failures, fixed 1.

---

**Tweet 5** (term2048 unmask)

on term2048: codemod fixed `imp.reload → importlib.reload` (surface error). Post-bump: 3 errors instead of 4.

Naive agent: "improvement, open PR."
Signature comparison: "2 new errors in new files, 1 fixed, 1 pre-existing — regression."

Pipeline correctly refused.

---

**Tweet 6** (LLM compliance fix)

When the LLM fixer ran on term2048, it wrapped `sys.stdin.fileno()` in try/except. Error count 3→1. But the remaining error changed type (new `AttributeError`).

The fix was worse by signature. Rollback triggered correctly.

---

**Tweet 7** (the tendency)

The LLM's instinct: compliance-fix, not root-cause. See failure → wrap in try/except → move on.

Coding equivalent of turning down a hard conversation. Suppress symptom, avoid cause.

Rollback caught it. Real fix: prompt the model to prefer understanding over wrapping.

---

**Tweet 8** (pycycle case)

on pycycle: baseline had 1 failing test. Post-bump: same test, same failure. Pre-existing bug.

Agent said: no_regression. Didn't claim credit for "fixing" the test.

Honest disclosure of pre-existing failures is better than silently masking them.

---

**Tweet 9** (what the agent won't do)

This agent refuses to:
- Open PRs when it introduced new failures
- Claim credit for pre-existing bugs
- Act on uncertain classifier verdicts
- Run under a personal account without disclosure

Each refusal is a design decision in code.

---

**Tweet 10** (the headline)

sometimes the right answer is to do nothing.

The most useful thing my AI agent did this week was refuse to open a PR.

---

**Tweet 11** (where the code is)

github.com/Selliksss/repo-revival-agent — MIT license, Python 3.12, Claude Opus 4.7, gh CLI

If you want to run it against your own dead repos, you can. If you want to discuss the refusal-as-feature design, DMs open.

---

---

*Build log: `BUILD_LOG.md` | Code: `github.com/Selliksss/repo-revival-agent`*