#!/usr/bin/env python3
"""Versioned, fail-closed machine adapter; lifecycle authority remains in engine."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import subprocess
import threading

import engine
from harness_registry import HarnessRegistryError, load_harness_metadata
from manager_paths import lexical_absolute, manager_home, venv_path, venv_python
from atm_bootstrap import runtime_unavailable_reason

PROTOCOL_VERSION = 1
MUTATIONS = ("install", "refresh", "remove", "repair")
INTERACTIVE = ("update", "recover")
READS = ("capabilities", "status", "check", "doctor")


class RequestError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RequestError(message)


def _parse(arguments):
    parser = Parser(prog="atm harness -- machine", add_help=False, allow_abbrev=False)
    parser.add_argument("--protocol", required=True)
    parser.add_argument("operation", choices=(*READS, *MUTATIONS, *INTERACTIVE))
    parser.add_argument("--harness", action="append", default=[])
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args(arguments)
    if args.operation in ("capabilities", "status", *INTERACTIVE) and args.harness:
        raise RequestError("this operation does not accept harness targets")
    if args.operation in READS and args.confirm:
        raise RequestError("read operations do not accept --confirm")
    if args.operation in MUTATIONS and not args.harness:
        raise RequestError("explicit --harness targets are required; there is no default or --all")
    return args


def _capabilities():
    registry = load_harness_metadata(repo_root=engine.REPO_ROOT)
    operations = {
        name: {"supported": True, "requiresConfirmation": False,
               "explicitHarnesses": False}
        for name in READS
    }
    operations.update({
        name: {"supported": True, "requiresConfirmation": True,
               "explicitHarnesses": True}
        for name in MUTATIONS
    })
    operations.update({
        name: {"supported": False, "requiresConfirmation": True,
               "explicitHarnesses": False,
               "reason": "interactive_confirmation_required"}
        for name in INTERACTIVE
    })
    operations["repair"]["scope"] = "existing-runtime-checkout-selected-harnesses"
    operations["repair"]["recoverySupported"] = False
    operations["repair"]["pathChanges"] = False
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "operations": operations,
        "harnesses": list(registry.choices),
        "instructionReplacement": "interactive-only",
        "statusObservation": "recorded-state-only",
    }


def _emit(operation, *, result=None, code=None, message=None, exit_code=0):
    print(json.dumps({
        "protocolVersion": PROTOCOL_VERSION,
        "operation": operation,
        "ok": code is None,
        "result": result,
        "error": {"code": code, "message": message} if code else None,
    }, ensure_ascii=False, sort_keys=True))
    return exit_code


LOG_LIMIT = 64 * 1024


def _run_lifecycle(command, environment):
    """Drain both pipes concurrently, retaining only bounded diagnostic tails.

    Cancellation belongs to the client process-tree owner: killing only this
    adapter could leave a mutating descendant alive. Never auto-retry a timeout.
    """
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=environment)
    tails = [bytearray(), bytearray()]
    totals = [0, 0]

    def drain(stream, index):
        with stream:
            while chunk := stream.read(8192):
                totals[index] += len(chunk)
                tails[index].extend(chunk)
                del tails[index][:-LOG_LIMIT]

    readers = [threading.Thread(target=drain, args=(stream, index), daemon=True)
               for index, stream in enumerate((process.stdout, process.stderr))]
    for reader in readers:
        reader.start()
    returncode = process.wait()
    for reader in readers:
        reader.join()
    result = subprocess.CompletedProcess(command, returncode,
                                         tails[0].decode("utf-8", errors="replace"),
                                         tails[1].decode("utf-8", errors="replace"))
    result.stdout_truncated = totals[0] > LOG_LIMIT
    result.stderr_truncated = totals[1] > LOG_LIMIT
    return result


def command_machine(namespace):
    operation = None
    try:
        args = _parse(namespace.machine_arguments)
        operation = args.operation
        if args.protocol != str(PROTOCOL_VERSION):
            return _emit(operation, code="unsupported_protocol", message="supported protocol: 1", exit_code=2)
        if operation == "capabilities":
            return _emit(operation, result=_capabilities())
        home = lexical_absolute(manager_home(namespace.home))
        if operation == "status":
            output = io.StringIO()
            warning = None
            try:
                load_harness_metadata(repo_root=engine.REPO_ROOT)
            except HarnessRegistryError as exc:
                warning = str(exc)
            with contextlib.redirect_stdout(output):
                engine.command_status(argparse.Namespace(home=str(home), json=True, registry_error=warning))
            return _emit(operation, result=json.loads(output.getvalue()))
        if operation in INTERACTIVE:
            return _emit(operation, code="confirmation_required",
                         message=f"{operation} requires the standalone interactive CLI; machine protocol 1 does not authorize it",
                         exit_code=3)
        registry = load_harness_metadata(repo_root=engine.REPO_ROOT)
        try:
            targets = sorted(set(registry.resolve_id(item) for item in args.harness))
        except ValueError as exc:
            raise RequestError(str(exc)) from exc
        if operation in MUTATIONS and not args.confirm:
            return _emit(operation, code="confirmation_required",
                         message="review the explicit harness targets, then pass --confirm for this operation only",
                         exit_code=3)
        # Do not bootstrap, repair PATH, initialize state or take another lock here.
        # The sole lifecycle owner acquires its lock and validates receipts/state.
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", GIT_OPTIONAL_LOCKS="0")
        reason = runtime_unavailable_reason(home, engine.REPO_ROOT / "scripts" / "engine.py", environment)
        if reason:
            return _emit(operation, code="operation_failed",
                         message=reason + "; run atm harness -- repair. No runtime repair was attempted.", exit_code=1)
        python = venv_python(venv_path(home))
        command = [str(python), "-B", str(engine.REPO_ROOT / "scripts" / "engine.py"),
                   "--home", str(home), operation, *targets]
        if operation in MUTATIONS:
            command.append("--yes")
        if operation in ("install", "refresh", "repair"):
            command.append("--machine-safe")
        if operation == "repair":
            command.append("--no-path")
        child = _run_lifecycle(command, environment)
        result = {"harnesses": targets, "exitCode": child.returncode,
                  "stdout": child.stdout, "stderr": child.stderr,
                  "stdoutTruncated": getattr(child, "stdout_truncated", False),
                  "stderrTruncated": getattr(child, "stderr_truncated", False)}
        if child.returncode:
            detail = child.stderr or child.stdout or "lifecycle command failed"
            code, exit_code = "operation_failed", 1
            if "confirmation_required:" in detail:
                code, exit_code = "confirmation_required", 3
            elif "another atm-harness mutation is already running:" in detail:
                code, exit_code = "busy", 4
            return _emit(operation, result=result, code=code, message=detail.strip(), exit_code=exit_code)
        return _emit(operation, result=result)
    except RequestError as exc:
        return _emit(operation, code="invalid_request", message=str(exc), exit_code=2)
    except (OSError, RuntimeError, ValueError, SystemExit) as exc:
        return _emit(operation, code="operation_failed", message=str(exc), exit_code=1)
