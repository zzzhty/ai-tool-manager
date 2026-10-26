# Fixture manifest validation SOP

Status: Ready

## Trigger

The operator requests validation of a generated fixture manifest in an isolated
test workspace and authorizes the bounded local repair below.

## Inputs

Use the supplied fixture source, generated manifest and verifier command from
the caller's isolated test workspace. All three are required inputs.

## Execution Harness

Run locally and serially in that workspace. Authoring or structurally checking
this document does not execute its steps.

## Allowed Actions

Read the supplied fixture source and manifest, run the supplied verifier, and
rebuild only that derived manifest within the isolated test workspace. Do not
change source inputs, publish, access the network or write outside that scope.

## Steps

### Step 1 - Validate the generated manifest

Action: Run the supplied verifier against the generated manifest.

Expected Output: Exit status zero with all required manifest checks passing.

Failure Handling: Use the shared stale-manifest recovery under Stop Conditions
only when diagnosis confirms that cause.

### Step 2 - Check the manifest digest

Action: Run the verifier's read-only digest check against the same manifest.

Expected Output: The digest matches the supplied fixture source.

Failure Handling: For a transient lock, pause dependent steps and inspect the
lock without writing. After evidence shows that the lock has cleared, retry
the same digest check once. Stop and report if that retry fails or the lock
does not clear; the stale-manifest rebuild is not a lock-recovery path.

### Step 3 - Report the verified result

Action: After both required checks pass, report their results and any recovery.

Expected Output: The report includes the original failure, diagnosis, bounded
recovery, revalidation results and any changed manifest path.

## Validation

Both required checks must pass unchanged before reporting success. A recovery
attempt, partial result or structural readiness check is not a passing result.

## Output Contract

Report commands, outputs, failure and recovery evidence, changed paths,
revalidation, blockers and residual risk.

## Stop Conditions

A user stop, missing required input, safety condition or permission boundary
stops the affected operation immediately, even when recovery is available.

Shared recovery: on a confirmed stale generated manifest, pause dependent
steps, diagnose against the unchanged fixture source, rebuild the derived
manifest once within the authorized workspace, then repeat Step 1's original
required validation. Continue only after it passes. If diagnosis cannot
establish that cause, the rebuild is unavailable or exhausted, validation
still fails, or recovery requires additional authority, stop and report the
evidence and needed input. Validation failures not covered by either declared
recovery path terminate directly.
