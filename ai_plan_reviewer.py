#!/usr/bin/env python3
"""
ai_plan_reviewer.py
-------------------
AI-powered Terraform plan risk analyzer using Claude (Anthropic).

Reads a `terraform plan` JSON output and returns a structured risk assessment
— flagging destructive changes, security concerns, and cost implications.

Usage:
    terraform plan -out=tfplan.binary
    terraform show -json tfplan.binary > tfplan.json
    python terraform/ai_plan_reviewer.py --plan tfplan.json

    # Or pipe directly:
    terraform show -json tfplan.binary | python terraform/ai_plan_reviewer.py --stdin

Requirements:
    pip install anthropic rich
    export ANTHROPIC_API_KEY=your_key
"""

import argparse
import json
import os
import sys
from collections import defaultdict

import anthropic
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()

RISK_COLORS = {
    "CRITICAL": "bold red",
    "HIGH": "red",
    "MEDIUM": "yellow",
    "LOW": "green",
    "INFO": "cyan",
}

DESTRUCTIVE_ACTIONS = {"delete", "replace"}


# ─── Plan Parsing ──────────────────────────────────────────────────────────────

def load_plan(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def extract_resource_changes(plan: dict) -> list[dict]:
    """Extract meaningful resource change data from terraform plan JSON."""
    changes = []
    for rc in plan.get("resource_changes", []):
        actions = rc.get("change", {}).get("actions", [])
        if actions == ["no-op"]:
            continue

        changes.append({
            "address": rc.get("address"),
            "type": rc.get("type"),
            "name": rc.get("name"),
            "actions": actions,
            "is_destructive": bool(DESTRUCTIVE_ACTIONS & set(actions)),
            "before": rc.get("change", {}).get("before"),
            "after": rc.get("change", {}).get("after"),
        })
    return changes


def build_summary(changes: list[dict]) -> dict:
    """Summarize changes by action type."""
    counts = defaultdict(int)
    for c in changes:
        for a in c["actions"]:
            counts[a] += 1

    destructive = [c for c in changes if c["is_destructive"]]
    return {
        "total": len(changes),
        "by_action": dict(counts),
        "destructive_count": len(destructive),
        "destructive_resources": [c["address"] for c in destructive],
    }


# ─── Claude Risk Analysis ──────────────────────────────────────────────────────

def analyze_plan_with_claude(changes: list[dict], summary: dict) -> str:
    """Send plan context to Claude for a structured risk review."""
    client_ai = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Truncate change details to avoid hitting context limits
    changes_preview = json.dumps(changes[:40], indent=2)

    prompt = f"""You are a senior DevOps/Platform Engineer reviewing a Terraform plan before it's applied to a production AWS environment.

Analyze the following plan and provide:

1. **Overall Risk Level**: CRITICAL / HIGH / MEDIUM / LOW
2. **Risk Summary**: 2-3 sentence overview of what this plan does and why it's risky or safe.
3. **Destructive Changes** (if any): List each destroy/replace action and explain blast radius.
4. **Security Concerns**: IAM changes, public exposure, encryption gaps, open security groups.
5. **Cost Impact**: Estimated cost increase/decrease based on resource types.
6. **Approval Recommendation**: APPROVE / APPROVE WITH CAUTION / BLOCK — with one-line reason.
7. **Pre-Apply Checklist**: 3-5 things the engineer should verify before running `terraform apply`.

---
PLAN SUMMARY:
{json.dumps(summary, indent=2)}

RESOURCE CHANGES (first 40):
{changes_preview}

Be direct and technical. Use markdown. Flag anything that could cause downtime or data loss in bold.
"""

    message = client_ai.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ─── Display ───────────────────────────────────────────────────────────────────

def display_summary_table(summary: dict):
    table = Table(title="📊 Plan Summary", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Total Changes", str(summary["total"]))
    for action, count in summary["by_action"].items():
        color = "red" if action in DESTRUCTIVE_ACTIONS else "green"
        table.add_row(f"  → {action.capitalize()}", f"[{color}]{count}[/{color}]")
    table.add_row("Destructive Resources", str(summary["destructive_count"]))

    console.print(table)

    if summary["destructive_resources"]:
        console.print("\n[bold red]⚠️  Destructive Resources:[/bold red]")
        for r in summary["destructive_resources"]:
            console.print(f"  [red]• {r}[/red]")
        console.print()


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AI-powered Terraform Plan Reviewer")
    parser.add_argument("--plan", help="Path to terraform plan JSON file")
    parser.add_argument("--stdin", action="store_true", help="Read plan JSON from stdin")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    if args.stdin:
        plan = json.load(sys.stdin)
    elif args.plan:
        plan = load_plan(args.plan)
    else:
        console.print("[red]Provide --plan <file> or --stdin[/red]")
        sys.exit(1)

    console.rule("[bold blue]🔍 Terraform AI Plan Reviewer[/bold blue]")

    with console.status("Parsing plan..."):
        changes = extract_resource_changes(plan)
        summary = build_summary(changes)

    display_summary_table(summary)

    if summary["total"] == 0:
        console.print("[green]✅ No changes detected in this plan.[/green]")
        sys.exit(0)

    with console.status("[bold green]🤖 Claude is reviewing your plan for risks..."):
        analysis = analyze_plan_with_claude(changes, summary)

    console.print(Panel(Markdown(analysis), title="🤖 Claude Risk Assessment", border_style="magenta"))
    console.print("\n[dim]Tip: Never run `terraform apply` without reviewing this output carefully.[/dim]")


if __name__ == "__main__":
    main()
