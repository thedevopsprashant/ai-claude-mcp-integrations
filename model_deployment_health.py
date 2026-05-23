#!/usr/bin/env python3
"""
model_deployment_health.py
--------------------------
MLOps: AI-powered ML model deployment health monitor for Kubernetes.

Monitors deployed ML model endpoints (e.g. TorchServe, Triton, FastAPI-based models)
running on EKS/K8s. Tracks latency, error rate, and throughput — and uses Claude
to flag drift indicators and recommend remediation.

Usage:
    python mlops/model_deployment_health.py --namespace ml-serving --interval 60
    python mlops/model_deployment_health.py --namespace ml-serving --model-label app=fraud-detector

Requirements:
    pip install anthropic kubernetes requests prometheus-client rich
    export ANTHROPIC_API_KEY=your_key
"""

import argparse
import json
import os
import statistics
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import anthropic
import requests
from kubernetes import client, config
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus-server:9090")


# ─── Data Models ───────────────────────────────────────────────────────────────

@dataclass
class ModelMetrics:
    model_name: str
    endpoint: str
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    requests_per_sec: float = 0.0
    error_rate: float = 0.0
    gpu_utilization: Optional[float] = None
    memory_usage_mb: float = 0.0
    prediction_confidence_avg: Optional[float] = None
    last_updated: str = ""
    history: deque = field(default_factory=lambda: deque(maxlen=20))

    def snapshot(self) -> dict:
        return {
            "latency_p50": self.latency_p50,
            "latency_p95": self.latency_p95,
            "error_rate": self.error_rate,
            "rps": self.requests_per_sec,
            "confidence": self.prediction_confidence_avg,
            "ts": self.last_updated,
        }


# ─── Prometheus Queries ────────────────────────────────────────────────────────

def query_prometheus(query: str) -> Optional[float]:
    """Run an instant PromQL query and return the first scalar result."""
    try:
        resp = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": query},
            timeout=5,
        )
        data = resp.json()
        results = data.get("data", {}).get("result", [])
        if results:
            return float(results[0]["value"][1])
    except Exception:
        pass
    return None


def fetch_model_metrics(model_name: str) -> dict:
    """Fetch metrics from Prometheus for a deployed model."""
    label = f'model="{model_name}"'
    return {
        "latency_p50": query_prometheus(f'histogram_quantile(0.50, rate(model_request_duration_seconds_bucket{{{label}}}[5m]))'),
        "latency_p95": query_prometheus(f'histogram_quantile(0.95, rate(model_request_duration_seconds_bucket{{{label}}}[5m]))'),
        "latency_p99": query_prometheus(f'histogram_quantile(0.99, rate(model_request_duration_seconds_bucket{{{label}}}[5m]))'),
        "rps": query_prometheus(f'rate(model_requests_total{{{label}}}[5m])'),
        "error_rate": query_prometheus(f'rate(model_errors_total{{{label}}}[5m]) / rate(model_requests_total{{{label}}}[5m])'),
        "confidence": query_prometheus(f'avg_over_time(model_prediction_confidence{{{label}}}[5m])'),
    }


# ─── Kubernetes: Discover Model Pods ──────────────────────────────────────────

def discover_model_deployments(namespace: str, label_selector: str = "mlops=true") -> list[dict]:
    """Find all ML model deployments in a namespace."""
    try:
        config.load_kube_config()
    except Exception:
        config.load_incluster_config()

    apps_v1 = client.AppsV1Api()
    deployments = apps_v1.list_namespaced_deployment(
        namespace=namespace, label_selector=label_selector
    )

    models = []
    for d in deployments.items:
        models.append({
            "name": d.metadata.name,
            "replicas": d.status.ready_replicas or 0,
            "desired": d.spec.replicas,
            "image": d.spec.template.spec.containers[0].image,
            "labels": d.metadata.labels or {},
        })
    return models


# ─── Drift Detection ──────────────────────────────────────────────────────────

def detect_drift(metrics_obj: ModelMetrics) -> list[str]:
    """Simple statistical drift detection based on metric history."""
    history = list(metrics_obj.history)
    if len(history) < 5:
        return []

    warnings = []

    # Latency drift
    latencies = [h.get("latency_p95", 0) for h in history if h.get("latency_p95")]
    if latencies and len(latencies) >= 3:
        recent_avg = statistics.mean(latencies[-3:])
        older_avg = statistics.mean(latencies[:-3])
        if older_avg > 0 and (recent_avg - older_avg) / older_avg > 0.3:
            warnings.append(f"⚡ Latency P95 increased {((recent_avg-older_avg)/older_avg*100):.0f}% over last {len(latencies)} intervals")

    # Confidence drift
    confidences = [h.get("confidence") for h in history if h.get("confidence") is not None]
    if len(confidences) >= 5:
        recent_conf = statistics.mean(confidences[-3:])
        older_conf = statistics.mean(confidences[:-3])
        if older_conf > 0 and (older_conf - recent_conf) / older_conf > 0.05:
            warnings.append(f"🎯 Prediction confidence dropped {((older_conf-recent_conf)/older_conf*100):.1f}% — possible data drift")

    # Error rate spike
    error_rates = [h.get("error_rate", 0) for h in history]
    if error_rates[-1] > 0.05:
        warnings.append(f"🔴 Error rate at {error_rates[-1]*100:.1f}% — investigate immediately")

    return warnings


# ─── Claude Analysis ───────────────────────────────────────────────────────────

def analyze_health_with_claude(models: list[ModelMetrics], all_warnings: dict) -> str:
    client_ai = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    model_summaries = []
    for m in models:
        model_summaries.append({
            "model": m.model_name,
            "latency_p95_ms": round((m.latency_p95 or 0) * 1000, 1),
            "error_rate_pct": round((m.error_rate or 0) * 100, 2),
            "rps": round(m.requests_per_sec or 0, 2),
            "confidence": m.prediction_confidence_avg,
            "warnings": all_warnings.get(m.model_name, []),
            "history_length": len(m.history),
        })

    prompt = f"""You are an MLOps engineer monitoring ML model deployments in production on Kubernetes.

Analyze the following model health data and provide:

1. **Overall Health Status**: HEALTHY / DEGRADED / CRITICAL
2. **Per-Model Assessment**: For each model, state what's concerning and why.
3. **Data Drift Risk**: Based on confidence trends and latency patterns, flag any drift risk.
4. **Recommended Actions**: Specific steps (rollback, scale up, retrain, circuit breaker, canary shift).
5. **Alerting Thresholds**: Suggest Prometheus alert rules for the observed patterns.

---
MODELS:
{json.dumps(model_summaries, indent=2)}

Be technical and specific. Reference model names. Use markdown.
"""

    message = client_ai.messages.create(
        model="claude-opus-4-5",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


# ─── Display ───────────────────────────────────────────────────────────────────

def build_metrics_table(models: list[ModelMetrics], warnings: dict) -> Table:
    table = Table(title="🧬 ML Model Deployment Health", header_style="bold blue")
    table.add_column("Model", style="cyan")
    table.add_column("Latency P50")
    table.add_column("Latency P95", style="yellow")
    table.add_column("Error Rate", style="red")
    table.add_column("RPS")
    table.add_column("Confidence")
    table.add_column("Status")

    for m in models:
        p95_ms = (m.latency_p95 or 0) * 1000
        err = (m.error_rate or 0) * 100
        conf = f"{m.prediction_confidence_avg:.2f}" if m.prediction_confidence_avg else "N/A"
        has_warnings = bool(warnings.get(m.model_name))

        status = "[red]⚠ WARN[/red]" if has_warnings else "[green]✅ OK[/green]"
        err_display = f"[red]{err:.2f}%[/red]" if err > 1 else f"{err:.2f}%"

        table.add_row(
            m.model_name,
            f"{(m.latency_p50 or 0)*1000:.0f}ms",
            f"[yellow]{p95_ms:.0f}ms[/yellow]" if p95_ms > 500 else f"{p95_ms:.0f}ms",
            err_display,
            f"{m.requests_per_sec:.1f}",
            conf,
            status,
        )

    return table


# ─── Main Loop ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MLOps Model Health Monitor")
    parser.add_argument("--namespace", default="ml-serving")
    parser.add_argument("--model-label", default="mlops=true", help="K8s label selector")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds")
    parser.add_argument("--analyze-every", type=int, default=5, help="Run Claude analysis every N polls")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]Error: ANTHROPIC_API_KEY not set.[/red]")
        sys.exit(1)

    console.rule("[bold blue]🧬 MLOps Model Health Monitor[/bold blue]")

    with console.status("Discovering model deployments..."):
        deployments = discover_model_deployments(args.namespace, args.model_label)

    if not deployments:
        console.print(f"[yellow]No model deployments found in namespace '{args.namespace}' with label '{args.model_label}'[/yellow]")
        sys.exit(0)

    console.print(f"[green]Found {len(deployments)} model deployment(s)[/green]\n")

    model_metrics = {
        d["name"]: ModelMetrics(model_name=d["name"], endpoint=f"http://{d['name']}.{args.namespace}.svc.cluster.local")
        for d in deployments
    }

    poll_count = 0
    while True:
        poll_count += 1
        all_warnings = {}

        for name, m in model_metrics.items():
            raw = fetch_model_metrics(name)
            m.latency_p50 = raw.get("latency_p50") or 0
            m.latency_p95 = raw.get("latency_p95") or 0
            m.latency_p99 = raw.get("latency_p99") or 0
            m.requests_per_sec = raw.get("rps") or 0
            m.error_rate = raw.get("error_rate") or 0
            m.prediction_confidence_avg = raw.get("confidence")
            m.last_updated = datetime.utcnow().isoformat()
            m.history.append(m.snapshot())
            all_warnings[name] = detect_drift(m)

        console.clear()
        console.print(build_metrics_table(list(model_metrics.values()), all_warnings))

        for model_name, warns in all_warnings.items():
            if warns:
                console.print(f"\n[bold yellow]⚠ Drift Warnings — {model_name}:[/bold yellow]")
                for w in warns:
                    console.print(f"  {w}")

        if poll_count % args.analyze_every == 0:
            console.print("\n")
            with console.status("[bold green]🤖 Running Claude health analysis..."):
                analysis = analyze_health_with_claude(list(model_metrics.values()), all_warnings)
            console.print(Panel(analysis, title="🤖 Claude MLOps Analysis", border_style="blue"))

        console.print(f"\n[dim]Next poll in {args.interval}s... (Ctrl+C to stop)[/dim]")
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitor stopped.[/yellow]")
