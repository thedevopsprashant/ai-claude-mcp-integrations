# 🤖 DevOps AI Toolkit — Powered by Claude & Python

> Automating infrastructure, reliability, and platform engineering with AI — real-world scripts used in production-grade DevOps workflows.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)](https://python.org)
[![AWS](https://img.shields.io/badge/AWS-EKS%20%7C%20EC2%20%7C%20S3-orange?logo=amazonaws)](https://aws.amazon.com)
[![Kubernetes](https://img.shields.io/badge/Kubernetes-Automation-326CE5?logo=kubernetes)](https://kubernetes.io)
[![Terraform](https://img.shields.io/badge/Terraform-IaC-7B42BC?logo=terraform)](https://terraform.io)
[![Claude AI](https://img.shields.io/badge/Claude-AI%20Powered-black?logo=anthropic)](https://anthropic.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## 🧠 What is this?

This repo is a collection of **AI-augmented DevOps automation scripts** that integrate **Claude AI (Anthropic)** with real infrastructure tools — Kubernetes, Terraform, AWS, Jenkins, and GitLab CI/CD. These aren't toy demos. They solve actual problems I've faced managing production infrastructure.

---

## 📁 Repository Structure

```
devops-ai-toolkit/
├── k8s/
│   ├── ai_pod_debugger.py          # AI-powered Kubernetes pod failure analyzer
│   └── smart_scaler.py             # Claude-assisted HPA recommendation engine
├── terraform/
│   ├── ai_plan_reviewer.py         # AI Terraform plan risk analyzer
│   └── drift_detector.py           # Infra drift detection + AI summary
├── aws/
│   ├── cost_optimizer.py           # AI-driven AWS cost anomaly detection
│   └── cloudwatch_analyzer.py      # AI log pattern analysis from CloudWatch
├── cicd/
│   ├── pipeline_failure_advisor.py # GitLab/Jenkins failure root cause AI advisor
│   └── release_notes_generator.py  # Auto-generate release notes from git diff
├── mlops/
│   ├── model_deployment_health.py  # Monitor ML model endpoints on K8s
│   └── drift_alert_pipeline.sh     # Shell pipeline for model drift alerting
├── scripts/
│   └── infra_chatbot.py            # Interactive CLI chatbot for infra queries
├── .github/
│   └── workflows/
│       └── ai_pr_review.yml        # AI-powered PR review GitHub Action
└── README.md
```

---

## 🚀 Featured Scripts

### 1. 🔍 AI Pod Debugger (`k8s/ai_pod_debugger.py`)
Automatically fetches failing pod logs from Kubernetes and sends them to Claude for root cause analysis. No more copy-pasting logs into ChatGPT manually.

```bash
python k8s/ai_pod_debugger.py --namespace production --pod-name api-server-xyz
```

**Output:**
```
🔴 Pod Status: CrashLoopBackOff
🤖 Claude Analysis:
  Root Cause: OOMKilled — container exceeded memory limit of 512Mi
  Recommendation: Increase memory limit to 1Gi or profile memory usage in the app
  Priority: HIGH
```

---

### 2. 📋 Terraform Plan Reviewer (`terraform/ai_plan_reviewer.py`)
Pipe your `terraform plan` output through Claude to get a risk assessment before applying changes to production.

```bash
terraform plan -out=tfplan.json && python terraform/ai_plan_reviewer.py --plan tfplan.json
```

---

### 3. 💰 AWS Cost Optimizer (`aws/cost_optimizer.py`)
Pulls AWS Cost Explorer data and uses Claude to identify anomalies, over-provisioned resources, and savings opportunities.

---

### 4. 🔁 GitLab CI/CD Failure Advisor (`cicd/pipeline_failure_advisor.py`)
Reads failed pipeline job logs via GitLab API and gives actionable fix suggestions using Claude.

---

### 5. 🧬 MLOps Model Health Monitor (`mlops/model_deployment_health.py`)
Monitors deployed ML model endpoints running on Kubernetes — tracks latency, error rates, and flags drift indicators.

---

## ⚙️ Setup

```bash
git clone https://github.com/YOUR_USERNAME/devops-ai-toolkit.git
cd devops-ai-toolkit

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export ANTHROPIC_API_KEY=your_claude_api_key
export AWS_PROFILE=your_aws_profile
export KUBECONFIG=~/.kube/config
export GITLAB_TOKEN=your_gitlab_token
```

---

## 🛠 Tech Stack

| Category | Tools |
|---|---|
| **Cloud** | AWS (EKS, EC2, S3, CloudWatch, Cost Explorer) |
| **Containers** | Kubernetes, Docker, Helm |
| **IaC** | Terraform, AWS CDK |
| **CI/CD** | GitLab CI/CD, Jenkins, GitHub Actions |
| **AI/ML** | Claude (Anthropic), LangChain, MLflow |
| **Language** | Python 3.11+, Bash/Shell |
| **Monitoring** | Prometheus, Grafana, CloudWatch |

---

## 🌐 Real-World Use Cases

- ✅ Reduced mean time to resolution (MTTR) for pod failures by **~60%** using AI-assisted log analysis
- ✅ Automated Terraform plan reviews before every production deployment
- ✅ Saved ~15% on AWS monthly bill through AI-flagged cost anomalies
- ✅ Cut release note prep time from 30 min → 2 min using git diff AI summarization

---

## 📌 Roadmap

- [ ] Slack bot integration for real-time infra Q&A
- [ ] LangChain-based agent for multi-step infrastructure remediation
- [ ] Model drift detection pipeline with automated retraining trigger
- [ ] Vector DB (ChromaDB) for infra runbook RAG chatbot

---

## 🤝 Contributing

PRs welcome! Open an issue first for major changes.

---

## 📄 License

MIT — use freely, attribution appreciated.
