# Demo SOP

Status: Ready

## Summary

Run a deterministic demo workflow.

## Trigger

The operator requests the demo.

## Preconditions

The repository is available.

## Working Directory

Use the repository root.

## Inputs

No external inputs.

## Execution Harness

Run locally and serially.

## Allowed Actions

Read files and run validation.

## Forbidden Actions

Do not publish changes.

## Steps

### Step 1 - Run the demo

Action:

Run the demo command.

Expected Output:

The command exits with status zero.

Failure Handling:

Stop and report the failing command.

Completion Criterion:

The zero exit status is recorded in the result.

## Validation

Require a zero exit code.

## Output Contract

Report the command and result.

## Stop Conditions

Stop on a failed required validation.

## Update Rules

Update this SOP when the command changes.

## Reuse Prompt

Execute this SOP exactly.

## Documented placeholder example

```text placeholder-example
Template syntax uses <sop-path> here.
```
