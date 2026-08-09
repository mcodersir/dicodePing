from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REQUIRED_PR_WORKFLOWS = ("ci.yml", "codeql.yml")
PASSING_CHECK_CONCLUSIONS = {"success", "neutral", "skipped"}
DEFAULT_SETUP_STATES = {"configured", "not-configured"}
REQUIRED_ASSET_TEMPLATES = (
    "dicodePing-v{version}-windows-x64.exe",
    "dicodePing-v{version}-linux-x86_64.tar.gz",
    "dicodePing-v{version}-macos-arm64.dmg",
    "dicodePing-v{version}-macos-x86_64.dmg",
    "dicodePing-v{version}-android.apk",
    "source.zip",
    "SHA256SUMS",
    "SBOM.spdx.json",
    "provenance.json",
)


class PublishError(RuntimeError):
    pass


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined(self) -> str:
        values = [value.strip() for value in (self.stdout, self.stderr) if value.strip()]
        return "\n".join(values)


class Publisher:
    def __init__(
        self,
        *,
        repository: str,
        workflow: str,
        tag: str,
        base_branch: str,
        error_report: Path | None,
    ) -> None:
        self.repository = repository
        self.workflow = workflow
        self.tag = tag
        self.base_branch = base_branch
        self.error_report = error_report
        self.report_lines: list[str] = []

    def log(self, message: str = "") -> None:
        print(message, flush=True)
        self.report_lines.append(message)

    def run_gh(
        self,
        args: Iterable[str],
        *,
        check: bool = False,
        echo: bool = False,
    ) -> CommandResult:
        command = ["gh", *[str(value) for value in args]]
        completed = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        result = CommandResult(command, completed.returncode, completed.stdout, completed.stderr)
        if echo and result.combined:
            self.log(result.combined)
        if check and result.returncode != 0:
            raise PublishError(
                f"Command failed ({result.returncode}): {' '.join(command)}\n{result.combined}"
            )
        return result

    def gh_json(self, args: Iterable[str]) -> Any:
        result = self.run_gh(args, check=True)
        try:
            return json.loads(result.stdout or "null")
        except json.JSONDecodeError as exc:
            raise PublishError(
                f"GitHub CLI returned invalid JSON for: {' '.join(result.args)}\n{result.combined}"
            ) from exc

    def save_error_report(self, message: str) -> None:
        if self.error_report is None:
            return
        self.error_report.parent.mkdir(parents=True, exist_ok=True)
        header = [
            "dicodePing v2.0.6 verified publisher failure",
            f"UTC: {datetime.now(timezone.utc).isoformat()}",
            f"Repository: {self.repository}",
            f"Tag: {self.tag}",
            "",
            message,
            "",
            "--- publisher output ---",
        ]
        self.error_report.write_text(
            "\n".join([*header, *self.report_lines]).rstrip() + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def parse_default_setup_state(payload: Any) -> str:
        if not isinstance(payload, dict):
            raise PublishError("GitHub returned an invalid CodeQL default-setup payload")
        state = str(payload.get("state") or "").strip().lower()
        if state not in DEFAULT_SETUP_STATES:
            raise PublishError(
                "GitHub returned an unknown CodeQL default-setup state: "
                f"{state or 'missing'}"
            )
        return state

    def default_setup_state(self) -> str:
        result = self.run_gh(
            [
                "api",
                "-H",
                "Accept: application/vnd.github+json",
                f"repos/{self.repository}/code-scanning/default-setup",
            ]
        )
        if result.returncode != 0:
            raise PublishError(
                "Unable to inspect the repository CodeQL setup. The verified publisher "
                "needs repository-admin access so it can prevent default setup and the "
                "checked-in advanced CodeQL workflow from running at the same time.\n"
                f"{result.combined}"
            )
        try:
            payload = json.loads(result.stdout or "null")
        except json.JSONDecodeError as exc:
            raise PublishError(
                "GitHub returned invalid JSON for the CodeQL default-setup configuration.\n"
                f"{result.combined}"
            ) from exc
        return self.parse_default_setup_state(payload)

    def ensure_advanced_codeql_setup(self, *, timeout_seconds: int = 240) -> None:
        """Keep one real CodeQL configuration: the checked-in advanced workflow.

        GitHub default setup and an advanced ``codeql.yml`` are mutually exclusive
        configurations. Leaving both active can produce two exact-SHA CodeQL checks:
        the advanced workflow may succeed while the default-setup check still fails.
        The publisher resolves that configuration conflict before creating a new PR
        head; it never suppresses a failure from the remaining advanced analysis.
        """
        state = self.default_setup_state()
        if state == "not-configured":
            self.log("[OK] CodeQL default setup is disabled; advanced codeql.yml is authoritative.")
            return

        self.log(
            "[CODEQL] GitHub default setup is configured while .github/workflows/codeql.yml "
            "provides advanced setup."
        )
        self.log(
            "[CODEQL] Disabling default setup so one complete advanced analysis remains; "
            "no CodeQL check is skipped."
        )

        last_error = ""
        for attempt in range(1, 6):
            result = self.run_gh(
                [
                    "api",
                    "-X",
                    "PATCH",
                    "-H",
                    "Accept: application/vnd.github+json",
                    f"repos/{self.repository}/code-scanning/default-setup",
                    "-f",
                    "state=not-configured",
                ]
            )
            if result.returncode == 0:
                break
            last_error = result.combined
            self.log(
                f"[WARN] CodeQL setup switch attempt {attempt}/5 failed; retrying..."
            )
            if last_error:
                self.log(last_error)
            time.sleep(min(30, attempt * 5))
        else:
            raise PublishError(
                "GitHub would not disable CodeQL default setup. Keep the checked-in "
                "advanced workflow and disable Default setup under Settings > Advanced "
                "Security, or update the organization security configuration that enforces it.\n"
                f"{last_error}"
            )

        deadline = time.monotonic() + timeout_seconds
        last_state = "configured"
        while time.monotonic() < deadline:
            try:
                last_state = self.default_setup_state()
            except PublishError as exc:
                last_error = str(exc)
                time.sleep(5)
                continue
            if last_state == "not-configured":
                self.log(
                    "[OK] CodeQL is now in advanced-setup mode. Future PR heads will have "
                    "one authoritative CodeQL analysis."
                )
                return
            self.log("[WAIT] GitHub is applying the CodeQL setup change...")
            time.sleep(5)

        suffix = f"\nLast API error: {last_error}" if last_error else ""
        raise PublishError(
            "Timed out waiting for CodeQL default setup to become not-configured; "
            f"last state was {last_state}.{suffix}"
        )

    def list_runs(
        self,
        *,
        workflow: str,
        event: str,
        commit: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        args = [
            "run",
            "list",
            "--repo",
            self.repository,
            "--workflow",
            workflow,
            "--event",
            event,
            "--limit",
            str(limit),
            "--json",
            "databaseId,status,conclusion,url,headSha,workflowName,createdAt,event",
        ]
        if commit:
            args.extend(["--commit", commit])
        payload = self.gh_json(args)
        return [item for item in (payload or []) if isinstance(item, dict)]

    def find_exact_run(
        self,
        *,
        workflow: str,
        event: str,
        commit: str,
        excluded_ids: set[int] | None = None,
    ) -> dict[str, Any] | None:
        excluded_ids = excluded_ids or set()
        runs = self.list_runs(workflow=workflow, event=event, commit=commit)
        matches = [
            run
            for run in runs
            if str(run.get("headSha") or "").lower() == commit.lower()
            and int(run.get("databaseId") or 0) not in excluded_ids
        ]
        matches.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
        return matches[0] if matches else None

    def wait_for_registered_run(
        self,
        *,
        workflow: str,
        event: str,
        commit: str,
        timeout_seconds: int,
        excluded_ids: set[int] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        last_error = ""
        while time.monotonic() < deadline:
            try:
                run = self.find_exact_run(
                    workflow=workflow,
                    event=event,
                    commit=commit,
                    excluded_ids=excluded_ids,
                )
                if run:
                    self.log(
                        f"[OK] Registered {workflow} run {run.get('databaseId')} for {commit[:12]}."
                    )
                    return run
            except PublishError as exc:
                last_error = str(exc)
                self.log(f"[WARN] Temporary run lookup error for {workflow}; retrying...")
            time.sleep(5)
        suffix = f"\nLast lookup error:\n{last_error}" if last_error else ""
        raise PublishError(
            f"Timed out waiting for {workflow} ({event}) at exact commit {commit}.{suffix}"
        )

    def run_state(self, run_id: int) -> dict[str, Any]:
        payload = self.gh_json(
            [
                "run",
                "view",
                str(run_id),
                "--repo",
                self.repository,
                "--json",
                "databaseId,status,conclusion,url,headSha,workflowName,createdAt,updatedAt",
            ]
        )
        if not isinstance(payload, dict):
            raise PublishError(f"Unexpected GitHub run payload for {run_id}")
        return payload

    def failed_run_log(self, run_id: int) -> str:
        result = self.run_gh(
            ["run", "view", str(run_id), "--repo", self.repository, "--log-failed"]
        )
        text = result.combined.strip()
        return text or "GitHub did not return failed-step logs."

    def wait_run_success(self, run: dict[str, Any], *, timeout_seconds: int = 7200) -> None:
        run_id = int(run.get("databaseId") or 0)
        if not run_id:
            raise PublishError("Workflow run is missing its database ID")
        deadline = time.monotonic() + timeout_seconds
        last_status = ""
        transient_errors = 0
        while time.monotonic() < deadline:
            try:
                state = self.run_state(run_id)
                transient_errors = 0
            except PublishError as exc:
                transient_errors += 1
                if transient_errors >= 6:
                    raise
                self.log(f"[WARN] Temporary GitHub status error for run {run_id}: {exc}")
                time.sleep(min(30, 5 * transient_errors))
                continue

            status = str(state.get("status") or "unknown")
            conclusion = str(state.get("conclusion") or "")
            display = conclusion if status == "completed" else status
            if display != last_status:
                self.log(f"[ACTIONS] {state.get('workflowName') or 'workflow'}: {display}")
                self.log(f"[ACTIONS] {state.get('url') or ''}")
                last_status = display

            if status == "completed":
                if conclusion == "success":
                    self.log(f"[OK] Workflow run {run_id} succeeded.")
                    return
                failure_log = self.failed_run_log(run_id)
                self.log("[FAILED STEP LOG]")
                self.log(failure_log)
                raise PublishError(
                    f"Workflow run {run_id} finished with conclusion '{conclusion}'.\n"
                    f"{state.get('url') or ''}\n\n{failure_log}"
                )
            time.sleep(10)
        raise PublishError(f"Timed out waiting for workflow run {run_id}")

    def wait_pr_workflows(self, *, head_sha: str) -> None:
        self.log("[8/10] Waiting for the exact CI and CodeQL runs...")
        runs: list[dict[str, Any]] = []
        for workflow in REQUIRED_PR_WORKFLOWS:
            runs.append(
                self.wait_for_registered_run(
                    workflow=workflow,
                    event="pull_request",
                    commit=head_sha,
                    timeout_seconds=600,
                )
            )
        for run in runs:
            self.wait_run_success(run)

    @staticmethod
    def classify_check_runs(
        payload: Any, *, head_sha: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        if not isinstance(payload, dict):
            raise PublishError("GitHub returned an invalid check-runs payload")
        raw_runs = payload.get("check_runs")
        if not isinstance(raw_runs, list):
            raise PublishError("GitHub check-runs payload does not contain check_runs")

        exact: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for item in raw_runs:
            if not isinstance(item, dict):
                continue
            item_sha = str(item.get("head_sha") or "")
            if item_sha.lower() != head_sha.lower():
                continue
            exact.append(item)
            status = str(item.get("status") or "").lower()
            conclusion = str(item.get("conclusion") or "").lower()
            if status != "completed":
                pending.append(item)
            elif conclusion not in PASSING_CHECK_CONCLUSIONS:
                failures.append(item)
        return exact, pending, failures

    @staticmethod
    def classify_commit_statuses(
        payload: Any,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        if payload is None:
            return [], [], []
        if not isinstance(payload, list):
            raise PublishError("GitHub returned an invalid commit-status payload")

        # Keep only the newest status for each context so an older failure
        # cannot override a newer success, even if an API/client changes order.
        ordered = [item for item in payload if isinstance(item, dict)]
        ordered.sort(
            key=lambda item: str(
                item.get("updated_at") or item.get("created_at") or ""
            ),
            reverse=True,
        )
        latest_by_context: dict[str, dict[str, Any]] = {}
        for item in ordered:
            context = str(item.get("context") or "").strip()
            if not context or context in latest_by_context:
                continue
            latest_by_context[context] = item

        latest = list(latest_by_context.values())
        pending: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for item in latest:
            state = str(item.get("state") or "").lower()
            if state == "pending":
                pending.append(item)
            elif state != "success":
                failures.append(item)
        return latest, pending, failures

    @staticmethod
    def check_detail(item: dict[str, Any]) -> str:
        app = item.get("app")
        app_slug = str(app.get("slug") or "") if isinstance(app, dict) else ""
        name = str(item.get("name") or item.get("context") or "unnamed check")
        status = str(
            item.get("conclusion")
            or item.get("state")
            or item.get("status")
            or "unknown"
        )
        url = str(
            item.get("html_url")
            or item.get("target_url")
            or item.get("details_url")
            or ""
        )
        source = f" [{app_slug}]" if app_slug else ""
        return f"- {name}{source}: {status} {url}".rstrip()

    @staticmethod
    def format_check_run_diagnostics(
        payload: Any, annotations: Any
    ) -> str:
        """Format a failed check's own output instead of guessing its cause."""
        if not isinstance(payload, dict):
            return ""
        output = payload.get("output")
        lines: list[str] = []
        if isinstance(output, dict):
            for label, key in (("Title", "title"), ("Summary", "summary"), ("Details", "text")):
                value = str(output.get(key) or "").strip()
                if value:
                    lines.append(f"{label}: {value}")
        if isinstance(annotations, list):
            rendered: list[str] = []
            for item in annotations[:20]:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path") or "").strip()
                start = item.get("start_line")
                end = item.get("end_line")
                location = path
                if start:
                    location += f":{start}"
                    if end and end != start:
                        location += f"-{end}"
                level = str(item.get("annotation_level") or "notice").upper()
                title = str(item.get("title") or "").strip()
                message = str(item.get("message") or "").strip()
                body = " — ".join(part for part in (title, message) if part)
                rendered.append(f"[{level}] {location or 'repository'}: {body}".rstrip())
            if rendered:
                lines.append("Annotations:\n" + "\n".join(rendered))
            if len(annotations) > 20:
                lines.append(f"Annotations: showing 20 of {len(annotations)}")
        return "\n".join(lines).strip()

    def failed_check_run_diagnostics(self, item: dict[str, Any]) -> str:
        check_id = int(item.get("id") or 0)
        if not check_id:
            return "GitHub did not expose a check-run ID for detailed diagnostics."
        try:
            payload = self.gh_json(
                [
                    "api",
                    "-H",
                    "Accept: application/vnd.github+json",
                    f"repos/{self.repository}/check-runs/{check_id}",
                ]
            )
            annotations = self.gh_json(
                [
                    "api",
                    "-H",
                    "Accept: application/vnd.github+json",
                    f"repos/{self.repository}/check-runs/{check_id}/annotations?per_page=100",
                ]
            )
        except PublishError as exc:
            return f"Unable to retrieve failed-check diagnostics: {exc}"
        formatted = self.format_check_run_diagnostics(payload, annotations)
        return formatted or "GitHub returned no title, summary, text, or annotations for this failed check."

    def exact_head_check_payloads(self, *, head_sha: str) -> tuple[Any, Any]:
        check_runs = self.gh_json(
            [
                "api",
                "-H",
                "Accept: application/vnd.github+json",
                f"repos/{self.repository}/commits/{head_sha}/check-runs?filter=latest&per_page=100",
            ]
        )
        statuses = self.gh_json(
            [
                "api",
                "-H",
                "Accept: application/vnd.github+json",
                f"repos/{self.repository}/commits/{head_sha}/statuses?per_page=100",
            ]
        )
        return check_runs, statuses

    def wait_all_pr_checks(
        self, *, pr_number: int, head_sha: str, timeout_seconds: int = 600
    ) -> None:
        # gh pr checks can surface a stale check from an older PR head or from
        # GitHub's synthetic merge commit. Query the Checks REST API by the
        # immutable release head SHA instead. Real failures on that exact SHA
        # still stop the publication.
        state = self.pr_state(pr_number)
        remote_head = str(state.get("headRefOid") or "")
        if remote_head.lower() != head_sha.lower():
            raise PublishError(
                f"PR head changed before check verification. Expected {head_sha}, "
                f"GitHub reports {remote_head or 'unknown'}."
            )

        deadline = time.monotonic() + timeout_seconds
        last_summary = ""
        transient_errors = 0
        while time.monotonic() < deadline:
            try:
                check_payload, status_payload = self.exact_head_check_payloads(
                    head_sha=head_sha
                )
                exact, pending_checks, failed_checks = self.classify_check_runs(
                    check_payload, head_sha=head_sha
                )
                latest_statuses, pending_statuses, failed_statuses = (
                    self.classify_commit_statuses(status_payload)
                )
                transient_errors = 0
            except PublishError as exc:
                transient_errors += 1
                if transient_errors >= 6:
                    raise
                self.log(
                    f"[WARN] Temporary exact-check lookup error for {head_sha[:12]}: {exc}"
                )
                time.sleep(min(30, transient_errors * 5))
                continue

            failures = [*failed_checks, *failed_statuses]
            pending = [*pending_checks, *pending_statuses]
            if failures:
                detail = "\n".join(self.check_detail(item) for item in failures)
                diagnostic_sections: list[str] = []
                for item in failed_checks:
                    name = str(item.get("name") or "unnamed check")
                    diagnostic_sections.append(
                        f"--- {name} check output ---\n"
                        + self.failed_check_run_diagnostics(item)
                    )
                diagnostics = (
                    "\n\n" + "\n\n".join(diagnostic_sections)
                    if diagnostic_sections
                    else ""
                )
                raise PublishError(
                    f"Checks for exact PR head {head_sha} failed:\n{detail}{diagnostics}"
                )

            # At least one check run must be visible. This prevents a temporary
            # empty API response from being mistaken for a fully green commit.
            if exact and not pending:
                self.log(
                    f"[OK] Exact head {head_sha[:12]} has "
                    f"{len(exact)} passing latest check run(s) and "
                    f"{len(latest_statuses)} passing commit status(es)."
                )
                return

            summary = (
                f"exact_sha={head_sha[:12]}, check_runs={len(exact)}, "
                f"commit_statuses={len(latest_statuses)}, pending={len(pending)}"
            )
            if summary != last_summary:
                self.log(f"[WAIT] Exact pull-request checks: {summary}")
                last_summary = summary
            time.sleep(5)

        raise PublishError(
            f"Timed out waiting for checks attached to exact PR head {head_sha}"
        )

    def pr_state(self, pr_number: int) -> dict[str, Any]:
        payload = self.gh_json(
            [
                "pr",
                "view",
                str(pr_number),
                "--repo",
                self.repository,
                "--json",
                "state,mergedAt,mergeCommit,headRefOid,mergeable,mergeStateStatus,url",
            ]
        )
        if not isinstance(payload, dict):
            raise PublishError(f"Unexpected pull-request payload for #{pr_number}")
        return payload

    @staticmethod
    def merge_commit_sha(state: dict[str, Any]) -> str:
        merge_commit = state.get("mergeCommit")
        if isinstance(merge_commit, dict):
            return str(merge_commit.get("oid") or "")
        return ""

    def merge_pr(self, *, pr_number: int, head_sha: str) -> str:
        self.log("[9/10] Merging the release PR with transient-error recovery...")
        last_error = ""
        for attempt in range(1, 6):
            state = self.pr_state(pr_number)
            if state.get("mergedAt"):
                merge_sha = self.merge_commit_sha(state)
                if not merge_sha:
                    raise PublishError("PR is merged but GitHub did not report the merge commit SHA")
                self.log(f"[OK] PR #{pr_number} is merged at {merge_sha}.")
                return merge_sha
            if str(state.get("state") or "").upper() == "CLOSED":
                raise PublishError(f"PR #{pr_number} was closed without being merged: {state.get('url')}")
            remote_head = str(state.get("headRefOid") or "")
            if remote_head.lower() != head_sha.lower():
                raise PublishError(
                    f"PR head changed unexpectedly. Expected {head_sha}, GitHub reports {remote_head}."
                )

            result = self.run_gh(
                [
                    "pr",
                    "merge",
                    str(pr_number),
                    "--repo",
                    self.repository,
                    "--squash",
                    "--match-head-commit",
                    head_sha,
                ]
            )
            if result.returncode != 0:
                last_error = result.combined
                self.log(
                    f"[WARN] Merge attempt {attempt}/5 returned an error; verifying the real PR state."
                )
                if last_error:
                    self.log(last_error)
            time.sleep(2)
            state = self.pr_state(pr_number)
            if state.get("mergedAt"):
                merge_sha = self.merge_commit_sha(state)
                if not merge_sha:
                    raise PublishError("PR merged but merge commit SHA is unavailable")
                self.log(f"[OK] PR #{pr_number} is merged at {merge_sha}.")
                return merge_sha
            if attempt < 5:
                time.sleep(min(40, attempt * 8))

        raise PublishError(
            f"PR #{pr_number} could not be merged after five verified attempts.\n"
            f"{last_error}\nhttps://github.com/{self.repository}/pull/{pr_number}"
        )

    def dispatch_release(self, *, merge_sha: str) -> dict[str, Any]:
        self.log("[10/10] Dispatching and verifying the four-platform stable release...")
        before = self.list_runs(workflow=self.workflow, event="workflow_dispatch", limit=50)
        excluded = {int(item.get("databaseId") or 0) for item in before}

        dispatch_error = ""
        for attempt in range(1, 4):
            result = self.run_gh(
                [
                    "workflow",
                    "run",
                    self.workflow,
                    "--repo",
                    self.repository,
                    "--ref",
                    self.base_branch,
                ]
            )
            if result.returncode == 0:
                break
            dispatch_error = result.combined
            self.log(f"[WARN] Workflow dispatch attempt {attempt}/3 failed; retrying...")
            self.log(dispatch_error)
            time.sleep(attempt * 5)
        else:
            raise PublishError(f"Unable to dispatch {self.workflow}:\n{dispatch_error}")

        run = self.wait_for_registered_run(
            workflow=self.workflow,
            event="workflow_dispatch",
            commit=merge_sha,
            timeout_seconds=300,
            excluded_ids=excluded,
        )
        self.log(f"[ACTIONS] Release run: {run.get('url') or ''}")
        self.wait_run_success(run)
        return run

    def tag_commit_sha(self) -> str:
        ref = self.gh_json(
            ["api", f"repos/{self.repository}/git/ref/tags/{self.tag}"]
        )
        if not isinstance(ref, dict) or not isinstance(ref.get("object"), dict):
            raise PublishError(f"Unable to resolve Git tag {self.tag}")
        object_type = str(ref["object"].get("type") or "")
        object_sha = str(ref["object"].get("sha") or "")
        if object_type == "commit":
            return object_sha
        if object_type == "tag":
            tag = self.gh_json(["api", f"repos/{self.repository}/git/tags/{object_sha}"])
            if isinstance(tag, dict) and isinstance(tag.get("object"), dict):
                return str(tag["object"].get("sha") or "")
        raise PublishError(f"Unsupported or incomplete Git tag object for {self.tag}")

    def verify_release(self, *, expected_commit: str | None, timeout_seconds: int = 900) -> str:
        version = self.tag[1:] if self.tag.startswith("v") else self.tag
        required_assets = {
            template.format(version=version) for template in REQUIRED_ASSET_TEMPLATES
        }
        deadline = time.monotonic() + timeout_seconds
        last_detail = "Release is not visible yet."

        while time.monotonic() < deadline:
            release_result = self.run_gh(
                ["api", f"repos/{self.repository}/releases/tags/{self.tag}"]
            )
            if release_result.returncode != 0:
                last_detail = release_result.combined or "Release is not visible yet."
                self.log("[WAIT] Stable release is not visible yet.")
                time.sleep(10)
                continue
            try:
                release = json.loads(release_result.stdout)
            except json.JSONDecodeError:
                last_detail = release_result.combined
                time.sleep(10)
                continue

            assets = release.get("assets") if isinstance(release, dict) else []
            asset_map: dict[str, int] = {}
            for item in assets or []:
                if isinstance(item, dict) and item.get("name"):
                    asset_map[str(item["name"])] = int(item.get("size") or 0)
            missing = sorted(required_assets.difference(asset_map))
            empty = sorted(name for name in required_assets if name in asset_map and asset_map[name] <= 0)

            latest_result = self.run_gh(
                ["api", f"repos/{self.repository}/releases/latest", "--jq", ".tag_name"]
            )
            latest_tag = latest_result.stdout.strip() if latest_result.returncode == 0 else ""

            try:
                tag_sha = self.tag_commit_sha()
            except PublishError as exc:
                tag_sha = ""
                last_detail = str(exc)

            stable = (
                isinstance(release, dict)
                and release.get("tag_name") == self.tag
                and release.get("draft") is False
                and release.get("prerelease") is False
            )
            latest = latest_tag == self.tag
            commit_ok = expected_commit is None or tag_sha.lower() == expected_commit.lower()
            if stable and latest and commit_ok and not missing and not empty:
                url = str(release.get("html_url") or f"https://github.com/{self.repository}/releases/tag/{self.tag}")
                self.log("[OK] Stable release is published, Latest, commit-matched and complete.")
                self.log(f"[OK] {url}")
                if os.environ.get("DICODEPING_PUBLISHER_NO_BROWSER") != "1":
                    opened = webbrowser.open(url, new=2)
                    if not opened and os.name == "nt":
                        os.startfile(url)  # type: ignore[attr-defined]
                return url

            details: list[str] = []
            if not stable:
                details.append("release is not a published stable release")
            if not latest:
                details.append(f"Latest points to {latest_tag or 'unknown'}")
            if not commit_ok:
                details.append(f"tag commit is {tag_sha or 'unknown'}, expected {expected_commit}")
            if missing:
                details.append("missing assets: " + ", ".join(missing))
            if empty:
                details.append("empty assets: " + ", ".join(empty))
            last_detail = "; ".join(details) or "release verification is still propagating"
            self.log(f"[WAIT] {last_detail}")
            time.sleep(10)

        raise PublishError(
            f"Workflow completed, but {self.tag} was not verified within the timeout: {last_detail}\n"
            f"https://github.com/{self.repository}/releases/tag/{self.tag}"
        )

    def publish(
        self,
        *,
        pr_number: int | None,
        head_sha: str,
        skip_pull_request: bool,
    ) -> str:
        if not skip_pull_request:
            if not pr_number:
                raise PublishError("A pull request number is required")
            self.wait_pr_workflows(head_sha=head_sha)
            self.wait_all_pr_checks(pr_number=pr_number, head_sha=head_sha)
            merge_sha = self.merge_pr(pr_number=pr_number, head_sha=head_sha)
        else:
            self.log("[INFO] Snapshot already matches main; skipping PR creation and resuming release.")
            merge_sha = head_sha

        self.dispatch_release(merge_sha=merge_sha)
        return self.verify_release(expected_commit=merge_sha)


def self_test() -> int:
    assert REQUIRED_PR_WORKFLOWS == ("ci.yml", "codeql.yml")
    assets = {template.format(version="2.0.6") for template in REQUIRED_ASSET_TEMPLATES}
    assert "dicodePing-v2.0.6-android.apk" in assets
    assert "provenance.json" in assets
    assert len(assets) == 9
    assert Publisher.parse_default_setup_state({"state": "configured"}) == "configured"
    assert (
        Publisher.parse_default_setup_state({"state": "not-configured"})
        == "not-configured"
    )
    try:
        Publisher.parse_default_setup_state({"state": "unexpected"})
    except PublishError:
        pass
    else:
        raise AssertionError("Unknown CodeQL setup states must fail closed")

    head = "a" * 40
    stale = "b" * 40
    check_payload = {
        "check_runs": [
            {"name": "CI", "head_sha": head, "status": "completed", "conclusion": "success"},
            {"name": "CodeQL", "head_sha": head, "status": "completed", "conclusion": "success"},
            {"name": "CodeQL", "head_sha": stale, "status": "completed", "conclusion": "failure"},
        ]
    }
    exact, pending, failures = Publisher.classify_check_runs(
        check_payload, head_sha=head
    )
    assert len(exact) == 2 and not pending and not failures

    statuses = [
        {
            "context": "external/security",
            "state": "failure",
            "updated_at": "2026-08-03T16:00:00Z",
        },
        {
            "context": "external/security",
            "state": "success",
            "updated_at": "2026-08-03T16:01:00Z",
        },
    ]
    latest, pending_statuses, failed_statuses = Publisher.classify_commit_statuses(statuses)
    assert len(latest) == 1 and not pending_statuses and not failed_statuses

    real_failure = {
        "check_runs": [
            {
                "name": "CodeQL",
                "head_sha": head,
                "status": "completed",
                "conclusion": "failure",
                "app": {"slug": "github-advanced-security"},
            }
        ]
    }
    _, _, failures = Publisher.classify_check_runs(real_failure, head_sha=head)
    assert len(failures) == 1
    diagnostic = Publisher.format_check_run_diagnostics(
        {
            "output": {
                "title": "Code scanning results",
                "summary": "1 new high severity alert",
                "text": "Resolve the alert before merging.",
            }
        },
        [
            {
                "path": "dicodeping/xray.py",
                "start_line": 914,
                "annotation_level": "failure",
                "title": "Certificate validation disabled",
                "message": "TLS certificates must be verified.",
            }
        ],
    )
    assert "1 new high severity alert" in diagnostic
    assert "dicodeping/xray.py:914" in diagnostic
    assert "Certificate validation disabled" in diagnostic
    print("Verified publisher self-test passed")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wait for exact GitHub checks, merge safely, run the release, verify assets, and open only a successful release."
    )
    parser.add_argument("--repo")
    parser.add_argument("--workflow", default="release.yml")
    parser.add_argument("--tag", default="v2.0.6")
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--head-sha")
    parser.add_argument("--skip-pr", action="store_true")
    parser.add_argument("--verify-existing-only", action="store_true")
    parser.add_argument("--ensure-codeql-advanced", action="store_true")
    parser.add_argument("--error-report", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    if not args.repo:
        print("[ERROR] --repo is required", file=sys.stderr)
        return 2
    if (
        not args.verify_existing_only
        and not args.ensure_codeql_advanced
        and not args.head_sha
    ):
        print("[ERROR] --head-sha is required", file=sys.stderr)
        return 2

    publisher = Publisher(
        repository=args.repo,
        workflow=args.workflow,
        tag=args.tag,
        base_branch=args.base_branch,
        error_report=args.error_report,
    )
    try:
        if args.ensure_codeql_advanced:
            publisher.ensure_advanced_codeql_setup()
        elif args.verify_existing_only:
            publisher.verify_release(expected_commit=None, timeout_seconds=60)
        else:
            publisher.publish(
                pr_number=args.pr,
                head_sha=args.head_sha,
                skip_pull_request=args.skip_pr,
            )
        return 0
    except (OSError, PublishError, subprocess.SubprocessError) as exc:
        message = str(exc)
        publisher.log(f"[ERROR] {message}")
        publisher.save_error_report(message)
        if args.error_report:
            publisher.log(f"[ERROR] Detailed report: {args.error_report}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
