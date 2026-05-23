#!/usr/bin/env python3
"""
ai_pod_debugger.py
------------------
AI-powered Kubernetes pod failure analyzer using Claude (Anthropic).

Fetches logs and events from a failing pod and gets a root cause analysis
+ actionable fix suggestions — directly in your terminal.

Usage:
    python ai_pod_debugger.py --namespace production --pod-name api-server-xyz
    python ai_pod_debugger.py --namespace staging --all-failing

Requirements:
    pip install anthropic kubernetes rich
    export ANTHROPIC_API_KEY=your_key
"""

import argparse
import os
import sys
from datetime import datetime

import anthropic
from kubernetes import client, config
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()

# ─── Kubernetes Helpers ────────────────────────────────────────────────────────

def load_kube_config():
    """Load kubeconfig from default location or in-cluster config."""
    try:
        config.load_kube_config()
    except config.ConfigException:
        config.load_incluster_config()  # Running inside a pod


def get_pod_logs(namespace: str, pod_name: str, tail_lines: int = 100) -> str:
    """Fetch the last N lines of logs from a pod (all containers)."""
    v1 = client.CoreV1Api()
    logs = []

    try:
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        containers = [c.name for c in pod.spec.containers]

        for container in containers:
            try:
                log = v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    container=container,
                    tail_lines=tail_lines,
                    previous=False,
                )
                logs.append(f"=== Container: {container} ===\n{log}")

                # Also try previous container logs if it crashed
                try:
                    prev_log = v1.read_namespaced_pod_log(
                        name=pod_name,
                        namespace=namespace,
                        container=container,
                        tail_lines=50,
                        previous=True,
                    )
                    logs.append(f"=== Previous Container ({container}) ===\n{prev_log}")
                except Exception:
                    pass

            except Exception as e:
                logs.append(f"=== Container: {container} — Could not fetch logs: {e} ===")

    except client.exceptions.ApiException as e:
        console.print(f"[red]Error fetching pod: {e}[/red]")
        sys.exit(1)

    return "\n\n".join(logs)


def get_pod_events(namespace: str, pod_name: str) -> str:
    """Fetch Kubernetes events related to a specific pod."""
    v1 = client.CoreV1Api()
    events = v1.list_namespaced_event(namespace=namespace)
    pod_events = [
        e for e in events.items if e.involved_object.name == pod_name
    ]

    if not pod_events:
        return "No events found."

    lines = []
    for e in pod_events:
        lines.append(
            f"[{e.type}] {e.reason}: {e.message} (count: {e.count}, last: {e.last_timestamp})"
        )
    return "\n".join(lines)


def get_pod_status(namespace: str, pod_name: str) -> dict:
    """Return basic pod status metadata."""
    v1 = client.CoreV1Api()
    pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
    phase = pod.status.phase
    conditions = pod.status.conditions or []
    container_statuses = pod.status.container_statuses or []

    statuses = []
    for cs in container_statuses:
        state_info = {}
        if cs.state.waiting:
            state_info = {"state": "Waiting", "reason": cs.state.waiting.reason}
        elif cs.state.running:
            state_info = {"state": "Running", "started": str(cs.state.running.started_at)}
        elif cs.state.terminated:
            state_info = {
                "state": "Terminated",
                "reason": cs.state.terminated.reason,
                "exit_code": cs.state.terminated.exit_code,
            }
        statuses.append({"container": cs.name, "ready": cs.ready, **state_info})

    return {"phase": phase, "conditions": [c.type for c in conditions], "containers": statuses}


def get_all_failing_pods(namespace: str) -> list[str]:
    """Return names of all non-Running or non-Succeeded pods in a namespace."""
    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod(namespace=namespace)
    failing = []
    for pod in pods.items:
        phase = pod.status.phase
        if phase not in ("Running", "Succeeded"):
            failing.append(pod.metadata.name)
    return failing


# ─── Claude Analysis ───────────────────────────────────────────────────────────

def analyze_with_claude(pod_name: str, namespace: str, logs: str, events: str, status: dict) -> str:
    """Send pod context to Claude for root cause analysis."""
    anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""You are a senior Site Reliability Engineer (SRE) with deep Kubernetes expertise.
Analyze the following Kubernetes pod failure and provide:

1. **Root Cause** — What is causing this failure? Be specific.
2. **Severity** — HIGH / MEDIUM / LOW with reasoning.
3. **Immediate Fix** — Exact steps or commands to resolve it right now.
4. **Long-term Recommendation** — How to prevent this in the future.
5. **Related Issues** — Any other potential problems you can infer.

---
Pod: {pod_name}
Namespace: {namespace}
Status: {status}

=== EVENTS ===
{events}

=== LOGS ===
{logs[:6000]}  # Truncated to fit context

Be concise, technical, and actionable. Use markdown formatting.
"""

    message = anthropic_client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ─── Display ───────────────────────────────────────────────────────────────────

def display_status_table(pod_name: str, status: dict):
    table = Table(title=f"Pod Status: {pod_name}", show_header=True, header_style="bold cyan")
    table.add_column("Container", style="cyan")
    table.add_column("State", style="yellow")
    table.add_column("Ready", style="green")
    table.add_column("Details")

    for c in status["containers"]:
        ready = "✅" if c.get("ready") else "❌"
        details = c.get("reason", c.get("started", c.get("exit_code", "")))
        table.add_row(c["container"], c.get("state", "Unknown"), ready, str(details))

    console.print(table)


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AI-powered Kubernetes Pod Debugger")
    parser.add_argument("--namespace", "-n", default="default", help="Kubernetes namespace")
    parser.add_argument("--pod-name", "-p", help="Pod name to debug")
    parser.add_argument("--all-failing", action="store_true", help="Debug all failing pods in namespace")
    parser.add_argument("--tail", type=int, default=100, help="Number of log lines to fetch")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]Error: ANTHROPIC_API_KEY environment variable not set.[/red]")
        sys.exit(1)

    load_kube_config()

    pod_names = []
    if args.all_failing:
        pod_names = get_all_failing_pods(args.namespace)
        if not pod_names:
            console.print(f"[green]✅ No failing pods found in namespace '{args.namespace}'.[/green]")
            sys.exit(0)
        console.print(f"[yellow]Found {len(pod_names)} failing pod(s): {pod_names}[/yellow]")
    elif args.pod_name:
        pod_names = [args.pod_name]
    else:
        console.print("[red]Provide --pod-name or --all-failing[/red]")
        sys.exit(1)

    for pod_name in pod_names:
        console.rule(f"[bold red]🔴 Analyzing: {pod_name}[/bold red]")

        with console.status(f"Fetching data for {pod_name}..."):
            status = get_pod_status(args.namespace, pod_name)
            logs = get_pod_logs(args.namespace, pod_name, tail_lines=args.tail)
            events = get_pod_events(args.namespace, pod_name)

        display_status_table(pod_name, status)

        with console.status("[bold green]🤖 Asking Claude for analysis..."):
            analysis = analyze_with_claude(pod_name, args.namespace, logs, events, status)

        console.print(Panel(Markdown(analysis), title="🤖 Claude AI Analysis", border_style="green"))
        console.print(f"\n[dim]Analysis generated at {datetime.utcnow().isoformat()}Z[/dim]\n")


if __name__ == "__main__":
    main()
