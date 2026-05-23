#!/usr/bin/env python3
"""
pipeline_failure_advisor.py
---------------------------
AI-powered GitLab CI/CD / Jenkins pipeline failure analyzer using Claude.

Fetches failed job logs from GitLab or Jenkins and provides root cause analysis
with exact fix steps — no more Googling cryptic CI errors.

Usage:
    # GitLab
    export GITLAB_TOKEN=your_token
    export GITLAB_URL=https://gitlab.com
    python cicd/pipeline_failure_advisor.py --gitlab --project-id 12345 --pipeline-id 67890

    # Jenkins
    export JENKINS_URL=https://jenkins.company.com
    export JENKINS_TOKEN=user:api_token
    python cicd/pipeline_failure_advisor.py --jenkins --job-name my-pipeline --build-number 42

Requirements:
    pip install anthropic requests rich
    export ANTHROPIC_API_KEY=your_key
"""

import argparse
import os
import sys
from base64 import b64encode

import anthropic
import requests
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()


# ─── GitLab Integration ────────────────────────────────────────────────────────

class GitLabClient:
    def __init__(self):
        self.base_url = os.environ.get("GITLAB_URL", "https://gitlab.com").rstrip("/")
        self.token = os.environ["GITLAB_TOKEN"]
        self.headers = {"PRIVATE-TOKEN": self.token}

    def get_pipeline_jobs(self, project_id: int, pipeline_id: int) -> list[dict]:
        url = f"{self.base_url}/api/v4/projects/{project_id}/pipelines/{pipeline_id}/jobs"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def get_failed_jobs(self, project_id: int, pipeline_id: int) -> list[dict]:
        jobs = self.get_pipeline_jobs(project_id, pipeline_id)
        return [j for j in jobs if j["status"] == "failed"]

    def get_job_log(self, project_id: int, job_id: int) -> str:
        url = f"{self.base_url}/api/v4/projects/{project_id}/jobs/{job_id}/trace"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.text

    def get_pipeline_info(self, project_id: int, pipeline_id: int) -> dict:
        url = f"{self.base_url}/api/v4/projects/{project_id}/pipelines/{pipeline_id}"
        resp = requests.get(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()


# ─── Jenkins Integration ───────────────────────────────────────────────────────

class JenkinsClient:
    def __init__(self):
        self.base_url = os.environ["JENKINS_URL"].rstrip("/")
        token = os.environ["JENKINS_TOKEN"]  # format: user:api_token
        self.auth_header = "Basic " + b64encode(token.encode()).decode()

    def _get(self, path: str) -> dict:
        resp = requests.get(
            f"{self.base_url}{path}",
            headers={"Authorization": self.auth_header},
        )
        resp.raise_for_status()
        return resp.json()

    def get_build_info(self, job_name: str, build_number: int) -> dict:
        return self._get(f"/job/{job_name}/{build_number}/api/json")

    def get_build_log(self, job_name: str, build_number: int) -> str:
        resp = requests.get(
            f"{self.base_url}/job/{job_name}/{build_number}/consoleText",
            headers={"Authorization": self.auth_header},
        )
        resp.raise_for_status()
        return resp.text

    def get_failed_stages(self, job_name: str, build_number: int) -> list[dict]:
        try:
            data = self._get(f"/job/{job_name}/{build_number}/wfapi/describe")
            return [s for s in data.get("stages", []) if s["status"] == "FAILED"]
        except Exception:
            return []


# ─── Claude Analysis ───────────────────────────────────────────────────────────

def analyze_failure_with_claude(
    platform: str,
    job_name: str,
    log: str,
    metadata: dict,
) -> str:
    client_ai = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Extract last 200 lines of log (most relevant for failures)
    log_tail = "\n".join(log.splitlines()[-200:])

    prompt = f"""You are an expert CI/CD engineer. Analyze this {platform} pipeline failure and provide:

1. **Failure Type**: (Build Error / Test Failure / Deploy Error / Infra Error / Auth Error / Timeout / Other)
2. **Root Cause**: Exact technical reason for the failure. Quote the specific error line.
3. **Fix Steps**: Step-by-step commands/changes to fix this. Be precise.
4. **Estimated Fix Time**: How long will this take to fix?
5. **Prevention**: How to prevent this failure in future pipelines (caching, retries, checks, etc.)
6. **Was this a Flaky Test?**: YES / NO / MAYBE — with reasoning.

---
Platform: {platform}
Job: {job_name}
Metadata: {metadata}

=== PIPELINE LOG (last 200 lines) ===
{log_tail}

Be direct. Reference the exact error messages. Use markdown. If it's a Docker/dependency/Terraform/test issue, say so explicitly.
"""

    message = client_ai.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ─── Display ───────────────────────────────────────────────────────────────────

def display_failed_jobs_table(jobs: list[dict]):
    table = Table(title="❌ Failed Jobs", header_style="bold red")
    table.add_column("Job ID", style="dim")
    table.add_column("Job Name", style="cyan")
    table.add_column("Stage", style="yellow")
    table.add_column("Duration")
    table.add_column("Failure Reason")

    for j in jobs:
        duration = f"{j.get('duration', 0):.0f}s"
        table.add_row(
            str(j["id"]),
            j["name"],
            j.get("stage", "N/A"),
            duration,
            j.get("failure_reason", "unknown"),
        )

    console.print(table)


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AI Pipeline Failure Advisor")
    # Platform
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--gitlab", action="store_true")
    group.add_argument("--jenkins", action="store_true")
    # GitLab args
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--pipeline-id", type=int)
    # Jenkins args
    parser.add_argument("--job-name")
    parser.add_argument("--build-number", type=int)
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    console.rule("[bold red]🔴 CI/CD Pipeline Failure Advisor[/bold red]")

    if args.gitlab:
        gl = GitLabClient()

        with console.status("Fetching GitLab pipeline data..."):
            failed_jobs = gl.get_failed_jobs(args.project_id, args.pipeline_id)
            pipeline_info = gl.get_pipeline_info(args.project_id, args.pipeline_id)

        if not failed_jobs:
            console.print("[green]✅ No failed jobs found in this pipeline.[/green]")
            sys.exit(0)

        display_failed_jobs_table(failed_jobs)

        for job in failed_jobs:
            console.rule(f"[yellow]Analyzing job: {job['name']}[/yellow]")
            with console.status(f"Fetching log for job {job['id']}..."):
                log = gl.get_job_log(args.project_id, job["id"])

            with console.status("🤖 Claude is diagnosing the failure..."):
                analysis = analyze_failure_with_claude(
                    platform="GitLab CI/CD",
                    job_name=job["name"],
                    log=log,
                    metadata={
                        "stage": job.get("stage"),
                        "failure_reason": job.get("failure_reason"),
                        "pipeline_ref": pipeline_info.get("ref"),
                        "pipeline_sha": pipeline_info.get("sha", "")[:8],
                    },
                )

            console.print(Panel(
                Markdown(analysis),
                title=f"🤖 Claude Analysis — {job['name']}",
                border_style="red",
            ))

    elif args.jenkins:
        jk = JenkinsClient()

        with console.status("Fetching Jenkins build data..."):
            build_info = jk.get_build_info(args.job_name, args.build_number)
            log = jk.get_build_log(args.job_name, args.build_number)
            failed_stages = jk.get_failed_stages(args.job_name, args.build_number)

        with console.status("🤖 Claude is diagnosing the Jenkins failure..."):
            analysis = analyze_failure_with_claude(
                platform="Jenkins",
                job_name=args.job_name,
                log=log,
                metadata={
                    "build_number": args.build_number,
                    "result": build_info.get("result"),
                    "duration_ms": build_info.get("duration"),
                    "failed_stages": [s["name"] for s in failed_stages],
                },
            )

        console.print(Panel(
            Markdown(analysis),
            title=f"🤖 Claude Analysis — {args.job_name} #{args.build_number}",
            border_style="red",
        ))


if __name__ == "__main__":
    main()
