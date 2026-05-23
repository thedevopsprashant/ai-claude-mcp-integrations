#!/usr/bin/env python3
"""
cost_optimizer.py
-----------------
AI-powered AWS cost anomaly detection and optimization advisor using Claude.

Pulls the last 30 days of AWS Cost Explorer data, identifies cost spikes,
and asks Claude to explain the anomalies and recommend savings actions.

Usage:
    python aws/cost_optimizer.py
    python aws/cost_optimizer.py --days 14 --threshold 20
    python aws/cost_optimizer.py --service EC2 --export report.md

Requirements:
    pip install anthropic boto3 rich
    export ANTHROPIC_API_KEY=your_key
    AWS credentials configured via profile or IAM role
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import anthropic
import boto3
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

console = Console()


# ─── AWS Cost Explorer ─────────────────────────────────────────────────────────

def get_daily_costs(days: int = 30, service_filter: str = None) -> list[dict]:
    """Fetch daily cost breakdown from AWS Cost Explorer."""
    ce = boto3.client("ce", region_name="us-east-1")

    end = datetime.utcnow().date()
    start = end - timedelta(days=days)

    filter_expr = {}
    if service_filter:
        filter_expr = {
            "Dimensions": {
                "Key": "SERVICE",
                "Values": [service_filter],
            }
        }

    kwargs = {
        "TimePeriod": {"Start": str(start), "End": str(end)},
        "Granularity": "DAILY",
        "Metrics": ["UnblendedCost"],
        "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
    }
    if filter_expr:
        kwargs["Filter"] = filter_expr

    response = ce.get_cost_and_usage(**kwargs)

    results = []
    for day in response["ResultsByTime"]:
        date = day["TimePeriod"]["Start"]
        for group in day["Groups"]:
            service = group["Keys"][0]
            cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
            if cost > 0.01:  # Skip negligible costs
                results.append({"date": date, "service": service, "cost": round(cost, 4)})

    return results


def detect_anomalies(costs: list[dict], threshold_pct: float = 20.0) -> list[dict]:
    """Detect days where cost spiked more than threshold% above 7-day average."""
    from collections import defaultdict

    by_service = defaultdict(list)
    for c in costs:
        by_service[c["service"]].append({"date": c["date"], "cost": c["cost"]})

    anomalies = []
    for service, entries in by_service.items():
        entries.sort(key=lambda x: x["date"])
        for i in range(7, len(entries)):
            window = [e["cost"] for e in entries[i - 7 : i]]
            avg = sum(window) / len(window)
            current = entries[i]["cost"]
            if avg > 0 and ((current - avg) / avg * 100) >= threshold_pct:
                anomalies.append({
                    "service": service,
                    "date": entries[i]["date"],
                    "cost": current,
                    "avg_7d": round(avg, 4),
                    "spike_pct": round((current - avg) / avg * 100, 1),
                })

    return sorted(anomalies, key=lambda x: x["spike_pct"], reverse=True)


def get_top_services(costs: list[dict], top_n: int = 10) -> list[dict]:
    """Summarize total spend by service."""
    from collections import defaultdict

    totals = defaultdict(float)
    for c in costs:
        totals[c["service"]] += c["cost"]

    ranked = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    return [{"service": s, "total_cost": round(v, 2)} for s, v in ranked[:top_n]]


# ─── Claude Analysis ───────────────────────────────────────────────────────────

def analyze_costs_with_claude(top_services: list[dict], anomalies: list[dict], days: int) -> str:
    """Ask Claude to interpret cost data and recommend savings."""
    client_ai = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    prompt = f"""You are an AWS FinOps specialist reviewing the last {days} days of cloud spend.

Analyze the cost data below and provide:

1. **Spend Overview**: Total spend context and which services dominate the bill.
2. **Anomaly Explanations**: For each cost spike, explain the likely cause (scaling event, data transfer, new deployment, etc.).
3. **Top 5 Savings Recommendations**: Specific, actionable steps with estimated savings % (Reserved Instances, Savings Plans, rightsizing, S3 lifecycle, NAT Gateway optimization, etc.).
4. **Immediate Actions**: 2-3 things to do this week to reduce costs.
5. **Risk Flags**: Any cost patterns that suggest misconfiguration or runaway resources.

---
TOP SERVICES BY SPEND:
{json.dumps(top_services, indent=2)}

DETECTED ANOMALIES (>{days}% spike over 7-day average):
{json.dumps(anomalies[:20], indent=2)}

Be specific. Reference actual AWS service names, pricing models, and tools (Cost Explorer, Trusted Advisor, Compute Optimizer). Use markdown.
"""

    message = client_ai.messages.create(
        model="claude-opus-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ─── Display ───────────────────────────────────────────────────────────────────

def display_top_services(top_services: list[dict]):
    table = Table(title="💰 Top AWS Services by Spend", header_style="bold cyan")
    table.add_column("Rank", style="dim", width=6)
    table.add_column("Service", style="cyan")
    table.add_column("Total Cost (USD)", style="bold white", justify="right")

    for i, s in enumerate(top_services, 1):
        cost_str = f"${s['total_cost']:,.2f}"
        color = "red" if s["total_cost"] > 1000 else "yellow" if s["total_cost"] > 100 else "green"
        table.add_row(str(i), s["service"], f"[{color}]{cost_str}[/{color}]")

    console.print(table)


def display_anomalies(anomalies: list[dict]):
    if not anomalies:
        console.print("[green]✅ No significant cost anomalies detected.[/green]")
        return

    table = Table(title="⚠️  Cost Anomalies Detected", header_style="bold red")
    table.add_column("Service", style="cyan")
    table.add_column("Date")
    table.add_column("Cost (USD)", justify="right")
    table.add_column("7d Avg", justify="right")
    table.add_column("Spike", style="red", justify="right")

    for a in anomalies[:10]:
        table.add_row(
            a["service"],
            a["date"],
            f"${a['cost']:,.2f}",
            f"${a['avg_7d']:,.2f}",
            f"[red]+{a['spike_pct']}%[/red]",
        )

    console.print(table)


# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AI-powered AWS Cost Optimizer")
    parser.add_argument("--days", type=int, default=30, help="Days of cost history to analyze")
    parser.add_argument("--threshold", type=float, default=20.0, help="Spike threshold %")
    parser.add_argument("--service", help="Filter to specific AWS service")
    parser.add_argument("--export", help="Export report to markdown file")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    console.rule("[bold yellow]💰 AWS AI Cost Optimizer[/bold yellow]")

    with console.status(f"Fetching {args.days} days of AWS Cost Explorer data..."):
        try:
            costs = get_daily_costs(days=args.days, service_filter=args.service)
        except Exception as e:
            console.print(f"[red]Failed to fetch cost data: {e}[/red]")
            console.print("[dim]Ensure AWS credentials are configured and Cost Explorer is enabled.[/dim]")
            sys.exit(1)

    top_services = get_top_services(costs)
    anomalies = detect_anomalies(costs, threshold_pct=args.threshold)

    display_top_services(top_services)
    console.print()
    display_anomalies(anomalies)
    console.print()

    with console.status("[bold green]🤖 Claude is analyzing your AWS spend..."):
        analysis = analyze_costs_with_claude(top_services, anomalies, args.days)

    console.print(Panel(Markdown(analysis), title="🤖 Claude Cost Optimization Report", border_style="yellow"))

    if args.export:
        with open(args.export, "w") as f:
            f.write(f"# AWS Cost Optimization Report\n\n")
            f.write(f"**Generated:** {datetime.utcnow().isoformat()}Z\n")
            f.write(f"**Period:** Last {args.days} days\n\n---\n\n")
            f.write(analysis)
        console.print(f"\n[green]✅ Report exported to {args.export}[/green]")


if __name__ == "__main__":
    main()
