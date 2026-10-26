# SOP recovery priority validation — 2026-10-15

> Pre-rebuild historical design and validation record. Repository commit IDs, PR
> numbers, installed-state observations and CI results below refer to the private
> pre-rebuild archive. They are not evidence for this repository's new root or
> current installation. Upstream release pins and attribution remain applicable.

Initial scope: local source maintenance on Home, based on main
`8b7b1e050f5f0701a557d28b099345d3e79f2a21`, branch
`fix/sop-recovery-priority`. No installed skills, user configuration or native
Goal runtime are execution targets. Publication was outside the initial
authorization. On 2026-10-15 the user subsequently authorized committing this
change, merging it into main and normal push, including the normal PR/CI route
when branch protection requires it. Installation remains outside scope.

## Evidence and frozen oracle

The baseline SOP Execute step 4 stops at the first failed required validation,
while Completion and the template permit step-local failure handling. This can
prevent an already declared and authorized repair from running. The Goal skill
already has adaptive recovery and phase gates; only its dependent-step wording
needs clarification.

The following oracle was fixed before source edits. Validation remains the same
after a recovery; a passing structural checker never grants action permissions.

| Case | Input / situation | Required outcome |
| --- | --- | --- |
| S1 Shared recovery | Required validation fails; the SOP declares an authorized shared diagnosis/repair path. | Pause dependent steps, apply that path, repeat the original validation, and resume dependencies only after it passes. |
| S2 Step-local recovery | A step declares one retry after diagnosis confirms a transient lock has cleared. | Use that bounded step-local path and unchanged revalidation; do not invent more attempts or invoke an unrelated shared repair. |
| S3 Exhaustion | The declared retry or repair limit is exhausted and validation still fails. | Stop the affected operation, report evidence and the needed input; do not borrow Goal's failure count. |
| S4 Permission gap | The apparent repair needs an out-of-scope write, external action or denied access. | Stop the affected action and report the missing authority; another tool or backend is not a workaround. |
| S5 Report-only | The SOP is report-only, and a proposed repair would write. | Keep recovery non-mutating; perform only declared authorized read-only diagnosis/retry, otherwise stop and report. |
| S6 User stop / safety | The user explicitly stops, or an explicit termination/safety condition occurs while recovery is available. | Honor the stop immediately; do not run that recovery. |
| S7 Terminating SOP | A Ready SOP explicitly stops on required validation failure and declares no recovery. | Stop and report; recovery and retries remain optional. |
| S8 Ready / structure | A SOP is Draft or lacks an existing required core section/step field. | Reject execution by default; do not add a new required recovery section, counter or schema. |
| G1 Authorized Goal repair | A required gate fails within the current milestone and an in-scope repair is authorized. | Pause dependent steps, continue current-milestone diagnosis/repair, and keep validation/review/advancement gates intact. |
| G2 Native stop / scope | The native runtime stops, an authorization boundary is reached, or a Sequence child remains incomplete. | Preserve the existing native hard stop and scope; do not reset counting, bypass access, advance a milestone or skip the child. |

## Candidate and review plan

Compare the no-change baseline with one minimal candidate: co-locate recovery
priority and its terminal boundaries in SOP Execute; align the optional template
guidance; clarify one Goal paragraph. Keep the immediate-stop SOP fixture and
existing checker behavior. Add a complete shared/step-local recovery fixture
and structural regression cases without exact-sentence instruction assertions.

Independent evaluation must cover both Standards and Spec, plus a separate
permission/safety counterexample pass. Report this semantic review separately
from structural checker tests. No live agent enactment or native Goal counting
is claimed by either static checks or document review.

## Validation results

- Baseline Workflow suite on unmodified main: 95 tests passed, no skips or
  existing failing tests observed. This structural baseline does not negate the
  source-level recovery contradiction above.
- Final candidate owning Workflow suite, rerun after the fixture correction:
  96 tests passed, no skips. The added test
  checks both complete SOP fixtures against Ready/Draft and existing required
  Allowed Actions, Validation and step output fields. It does not assert exact
  skill sentences or simulate an agent executing recovery.
- Readiness checks passed for the preserved terminating `ready_sop.md` and the
  new shared/step-local `ready_sop_with_recovery.md` fixture.
- SOP and Goal relative-link checks, Workflow plugin validation, and
  `git diff --check` passed.
- Runner: existing Python 3.13.15 tooling venv; test HOME/USERPROFILE and client
  environment overrides were isolated. No system component was installed.

Final integration results on Home Linux, after identity generation:

| Suite | Collected | Passed | Skipped | Failed |
| --- | ---: | ---: | ---: | ---: |
| Root `tests` | 462 | 453 | 9 | 0 |
| Watcher | 87 | 84 | 3 | 0 |
| Workflow (owning run before generation) | 96 | 96 | 0 | 0 |

The 12 skips are platform-dependent Windows batch/PowerShell, extended-path,
encoding and native case-insensitive-filesystem cases. They were not exercised
on this Linux host. No existing failing tests were observed in the baseline
Workflow or final suites. All three source-plugin validators, four README
JSON syntax checks, Python compilation for the CI source directories,
distribution identity validation and final diff hygiene passed. Compilation
used a temporary pycache prefix outside the repository.

Supporting logs are outside the repository at
`../validation/sop-recovery/` relative to its root. In particular,
`baseline-workflow-tests.log`, `postfix-owning-results.json`,
`postfix-workflow-owning.log`, `integration-results.json`,
`integration-root-tests.log`, `integration-watcher-tests.log`,
`distribution-generation.log` and `final-static-checks.log` retain the actual
results. Earlier candidate logs precede the fixture correction; the `postfix-`
logs describe the final packaged source.

## Independent semantic review

The first read-only Standards/Spec review covered all modified and untracked
source files, the baseline and S1–S8/G1–G2. Its separate permission/safety pass
found no additional boundary regression. It identified one P2 Spec issue in the
new fixture: the generic terminal clause could override Step 2's declared lock
recovery. The fixture now limits direct termination to failures covered by
neither declared recovery path. The same independent reviewer re-read the net
diff and all S1–S8/G1–G2 cases: no remaining Standards or Spec findings. The
separate permission/safety counterexamples still reject out-of-scope writes,
unauthorized external actions, denied-access workarounds, report-only writes,
recovery after a user/runtime stop, and skipping an incomplete Sequence child.

This finding was not caught by passing readiness/structure tests. Semantic review
does not establish live agent adherence or native Goal runtime behavior.

## Distribution and final scope

After the final packaged-source fix, fresh owning tests and semantic re-review,
`scripts/update_plugin_generations.py` ran exactly once for this change. The
read-only identity checker and an independent generated-only review both
confirmed the resulting single current identity:

- Workflow: `1.0.0+codex.45dfd6fc0590d8fe`
- Workflow content SHA-256:
  `45dfd6fc0590d8fe6a5038900ebe5c23a17cc715c90daaf07c4c0c6e1fcfa3cb`
- Bundle:
  `sha256:253c37ad00098629da98f089ba65da47dcdc1d39e1d109a76e42f0b8ba45da64`

Only Workflow's manifest and the distribution identity ledger changed as
generated files. Marketplace still points to `./plugins/workflow` and has no
separate version field. Matt, Watcher and release `VERSION` remain unchanged.

The source diff consists of SOP Execute/Completion guidance, its template,
one Goal paragraph, the Workflow README, changelog, the structural regression
test, one new recovery fixture and this local validation record. The previous
terminal SOP fixture, readiness checker/schema, Goal native counting,
references/templates, advancement and Sequence rules remain unchanged.

At the local-verification checkpoint, changes were uncommitted and unstaged on
`fix/sop-recovery-priority` at the recorded main base, with no publication or
installation performed. The user's later publication authorization is recorded
above; the corresponding Git history, PR and CI report capture that outcome.
No installation or real-user configuration change is part of this work. There
is no remaining local implementation blocker.
This is source/structure validation and independent semantic review, not a
live agent enactment, native Goal runtime test or macOS/Windows run. No claim
is made about native retry counting or runtime adherence.


## Current-root revision — 2026-10-22

This section records current maintenance; the earlier results remain historical.
Source: the repository checkout of
`zzzhty/oh-my-harness` (API ID `1429274611`), clean `main` at
`7a5a5ead3b32446669894700a5a9f162c241bd3f` before edits. Local `origin/main`
matched HEAD. The initial scope was uncommitted SOP guidance, template and
this existing owner record, plus required generated content identities. At
that checkpoint, installation, activation, release, commit, push and tag
operations were outside scope.

### Evidence and frozen acceptance scenarios

The user supplied two execution summaries: 62 browser cases and specialty
checks had passed before two screenshots were added; another attempt passed
browser checks but failed final database/event readback. These are review
inputs, not runs performed or independently reproduced here. The current
skill and template both require repeating "unchanged" validation without
separating acceptance criteria from evidence coverage.

The following seven scenarios were fixed before drafting the candidate:

| Case | Situation | Required outcome |
| --- | --- | --- |
| R1 | A passed, B failed, C is pending. | Preserve failure/diagnosis evidence; repair through the declared authorized path, revalidate B and affected coverage/prerequisites, reuse still-valid A under its owner/verifier, then continue C when dependencies close. Independent authorized work may continue. |
| R2 | Repair affects A's dependencies, or later validation fails. | Reassess A's coverage; earlier success cannot override later failure or relax exact-source, dependency, configuration, environment or acceptance bindings. |
| R3 | A new attempt requires seed and final readback in that attempt. | Reestablish fixtures, identity, resources and leases; complete required order, fresh admission, business operations, final readback and cleanup. Do not splice old mutable state into qualification or hot-edit a running candidate. |
| R4 | The owner requires a complete fresh run, transactional rollback or explicit termination. | Follow those gates; partial evidence cannot replace the required full run, transaction or stop. |
| R5 | Only metadata/screenshots change, or execution changes phase/session/namespace. | Assess actual coverage changes; supplement affected checks without automatically repeating unrelated training, Demo, review or browser work. A label change alone neither invalidates evidence nor resets a budget. |
| R6 | The same failure has no repair, relevant input change or new diagnosis; recovery is exhausted. | Do not blindly retry or reset the original budget. Stop the affected action and report evidence and needed input. |
| R7 | Authoring, report-only work, Draft status or insufficient permission. | Preserve mode, Ready and authorization gates; authoring and passing document checks grant no execution rights. Recovery adds no permissions. |

### Baseline and review plan

No-op preserves the existing mode and immediate-stop rules, but leaves reuse,
invalidation, fresh-attempt state and proportional revalidation unspecified
(R1–R3/R5), and does not address blind retries or budget resets (R6). Reject
no-op against this oracle. Compare it with one bounded wording candidate in
Create Or Update, Execute item 4 and template Stop Conditions. Keep recovery
optional and the eight-section structural checker unchanged; no new fields,
recovery files, ledgers, skip paths or word-matching tests.

Use independent read-only Standards/Spec review of the raw evidence, frozen
scenarios and net diff, including permission and failure counterexamples.
Record semantic conclusions separately from maintenance checks; neither is a
live SOP execution or proof of agent runtime behavior.


### Selected revision and current review results

Selected the minimal wording patch: Create Or Update item 5 describes evidence,
invalidation, remaining work and prerequisites only for applicable continuation
workflows; Execute item 4 separates acceptance criteria from execution coverage;
the template carries the same optional recovery rules. No new section, field,
recovery file, resume mechanism, skip path or verifier was introduced.

Independent read-only Standards/Spec review compared HEAD with the patch.
A focused counterexample qualified its initial no-findings conclusion: the
new-attempt sentence could imply mandatory final readback/cleanup for a simple
inspect-and-report SOP. Both skill and template now scope those obligations to
the original owner's applicable requirements. Targeted re-review confirmed that
the counterexample is resolved, with no changed oracle verdict or remaining
material finding. No tests or workflows ran in either reviewer pass.

| Case | No-op HEAD | Final semantic conclusion |
| --- | --- | --- |
| R1 | Partial: evidence reuse/prerequisites ambiguous. | Pass: reuse valid A; repair/revalidate B and affected coverage before dependent C. |
| R2 | Partial: reassessment implicit. | Pass: reassess changed bindings; old passes cannot override later failure. |
| R3 | Partial: attempt-state safeguards unstated. | Pass: applicable fresh/state/order/operations/readback/cleanup requirements remain binding. |
| R4 | Pass. | Pass: original fresh/full, transaction/rollback and termination gates prevail. |
| R5 | Ambiguous rerun scope. | Pass: actual coverage determines revalidation; labels alone do not invalidate passes. |
| R6 | Partial: blind retries and budget resets unstated. | Pass: no blind same-cause retries or renamed budgets; exhaustion stops the affected action. |
| R7 | Pass. | Pass: authoring, report-only, Ready and permission boundaries remain intact. |

"Partial" describes missing generic guidance, not a reproduced violation by an
existing SOP. Separate permission/failure counterexamples covered out-of-scope
recovery, report-only writes, explicit/user stops, old browser evidence plus
failed same-attempt DB/event readback, owner-required complete fresh runs and
rollback. None permits bypassing a binding or certifying success from old
mutable state. Simple SOPs gain no undeclared recovery or state obligations.

### Current maintenance checks and identities

Runner: existing Python 3.13.15 tooling interpreter, with
`PYTHONDONTWRITEBYTECODE=1` and `-B`; no dependency installation or managed
installation change. The archived checks above were not treated as current-root
evidence.

| Check actually run | Result |
| --- | --- |
| `python -m unittest discover -s plugins/workflow/tests -p 'test_*.py'` | 96 passed in 18.987s; no skips/failures. Ran once. |
| `check_sop_ready.py` on `ready_sop.md` and `ready_sop_with_recovery.md` | Both Ready contracts passed; procedure actions were not run. |
| `check_sop_links.py plugins/workflow/skills/sop` | Passed. |
| `scripts/validate_plugin.py plugins/workflow` | Passed. |
| `scripts/update_plugin_generations.py` | Completed exactly once without a release-version argument. |
| `scripts/check_plugin_generations.py` | Passed for the single current identity. |
| Generated JSON diff inspection and `git diff --check` | Passed; only the expected identity fields changed. |

The 96-test run preceded the narrow owner-applicability clarification. Its
structural coverage remains valid: no checker, schema, required field, fixture,
invocation policy or tested mode gate changed. Existing Ready/link/plugin checks
also retain their coverage; the later metadata has its own identity check.
Per the user's continuation instruction, these passing tests were reused rather
than repeated. A model-capacity interruption was not a test failure or a retry
budget reset.

Root AGENTS.md requires generation after packaged-content edits; README's
Release And Plugin Distribution Identity section defines this as deterministic
local metadata. The read-only preflight showed only Workflow needed a new
content generation. The generator changed only its manifest `version` and the
ledger's Workflow `contentSha256`, `generation`, `version` and `bundleIdentity`.
Release `VERSION` remains `1.0.0`; other plugins, marketplace/install manifests,
identity semantics and hashing algorithm are unchanged. Historical identities
above remain historical and were not rewritten.

- Workflow: `1.0.0+codex.ce1d34b52cbee17d`
- Workflow SHA-256: `ce1d34b52cbee17dd31af6f0d65787dcd4e619ec83b8a907c7433c9b71335e33`
- Bundle: `sha256:07ea05524b329a5dc10de1ad4aff58421311a38f0f186f97acd29c80a9f3f87b`

### Current scope and limits

The final local change is limited to the skill, its template, this existing
maintenance record, Workflow's generated manifest version and the distribution
identity ledger. At the validation checkpoint, HEAD remained the recorded
root; all changes were unstaged and uncommitted. There were no pre-existing changes at the initial checkpoint.
The readiness checker remains a structural check; no tests, fixtures or scripts
were added or changed.

During that validation checkpoint, no SOP business workflow, browser,
training, Demo, product, release or deployment flow ran. Root/Watcher suites and unrelated integration checks were not rerun.
No plugin install, activation, publication, Git commit, push or tag occurred;
legacy source, managed installations and plugin caches were not edited. There
is no remaining maintenance blocker. Semantic review and structural checks do
not establish live agent adherence or reproduce the user's reported executions.

The user subsequently authorized committing these five reviewed files, folding
them into the initial commit and synchronizing the source repository. This
does not authorize plugin installation, activation, tags or a plugin release.
