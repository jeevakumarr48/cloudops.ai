"""CloudOps AI backend API.

Read-only cloud intelligence: AWS operational data, cost data,
infrastructure-as-code changes, and deterministic rules are combined into
explainable recommendations. AI explains findings; it never decides and never
performs AWS actions.
"""

import os
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aws_client import AWSAccessError, discover_ec2_instances
from services.ai_explainer import explain_findings
from services.aws_metrics import MetricsUnavailableError, get_ec2_metrics
from services.cost_service import CostServiceError, get_cost_summary
from services.decision_engine import (
    analyze_ec2_resources,
    analyze_iac_changes,
    normalize_metrics,
)
from services.iac_analyzer import (
    IaCPlanError,
    infracost_status,
    normalize_infracost,
    parse_plan,
)

app = FastAPI(
    title="CloudOps AI API",
    description="AWS resource discovery and cloud optimization platform",
    version="1.0.0"
)

_cors_origins = [origin.strip() for origin in os.environ.get(
    "CLOUDOPS_AI_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _unavailable(error: Exception, status_code: int = 503) -> JSONResponse:
    """Return a structured, secret-free error payload."""
    return JSONResponse(
        status_code=status_code,
        content={"status": "unavailable", "error": str(error)},
    )


def _legacy_recommendation(finding: Dict[str, Any]) -> Dict[str, Any]:
    """Project a finding onto the original recommendation field set."""
    return {
        "resource_id": finding.get("resource_id"),
        "resource_type": finding.get("resource_type"),
        "severity": finding.get("severity"),
        "issue": finding.get("issue"),
        "recommendation": finding.get("recommendation"),
        "estimated_monthly_savings": finding.get("estimated_monthly_savings"),
        "tags": finding.get("tags", {}),
    }


def _severity_counts(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0}
    for finding in findings:
        key = (finding.get("severity") or "").lower()
        if key in counts:
            counts[key] += 1
    return counts


def _collect_instances(
    region: Optional[str] = None,
) -> tuple[List[Dict[str, Any]], Optional[JSONResponse]]:
    """Collect EC2 instances, returning an error response on failure."""
    try:
        return discover_ec2_instances(region), None
    except AWSAccessError as error:
        return [], _unavailable(error)


def _collect_metrics(
    instance_ids: List[str], region: Optional[str], hours: int
) -> tuple[List[Dict[str, Any]], Optional[JSONResponse]]:
    try:
        return get_ec2_metrics(instance_ids, region_name=region, hours=hours), None
    except MetricsUnavailableError as error:
        return [], _unavailable(error)


@app.get("/")
def home():
    return {
        "message": "CloudOps AI API is running",
        "status": "healthy"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


@app.get("/api/resources/ec2")
def get_ec2_resources(region: Optional[str] = None):
    raw_instances, error_response = _collect_instances(region)
    if error_response is not None:
        return error_response

    instances = []

    for instance in raw_instances:
        tags = {
            tag["Key"]: tag["Value"]
            for tag in instance.get("Tags", [])
        }

        instances.append({
            "instance_id": instance.get("InstanceId"),
            "instance_type": instance.get("InstanceType"),
            "state": instance.get("State", {}).get("Name"),
            "availability_zone": instance.get(
                "Placement", {}
            ).get("AvailabilityZone"),
            "launch_time": str(instance.get("LaunchTime")),
            "tags": tags
        })

    return {
        "total_instances": len(instances),
        "instances": instances
    }


@app.get("/api/metrics/ec2")
def get_ec2_metrics_endpoint(hours: int = 24, region: Optional[str] = None):
    raw_instances, error_response = _collect_instances(region)
    if error_response is not None:
        return error_response

    instance_ids = [instance.get("InstanceId") for instance in raw_instances]
    metrics, error_response = _collect_metrics(instance_ids, region, hours)
    if error_response is not None:
        return error_response

    return {
        "total_instances": len(instance_ids),
        "period_hours": hours,
        "metrics": metrics,
    }


@app.get("/api/costs")
def get_costs(period: str = "monthly", group_by_service: bool = True):
    try:
        return get_cost_summary(period=period, group_by_service=group_by_service)
    except CostServiceError as error:
        return _unavailable(error)


@app.get("/api/insights")
def get_insights(hours: int = 24, region: Optional[str] = None):
    raw_instances, error_response = _collect_instances(region)
    if error_response is not None:
        return error_response

    instance_ids = [instance.get("InstanceId") for instance in raw_instances]
    metrics, metrics_error = _collect_metrics(instance_ids, region, hours)

    metrics_by_instance = {
        metric["instance_id"]: metric for metric in metrics if metric.get("instance_id")
    }
    findings = analyze_ec2_resources(raw_instances, metrics_by_instance=metrics_by_instance)
    explanation = explain_findings(findings)

    payload: Dict[str, Any] = {
        "status": "ok",
        "metrics_status": "unavailable" if metrics_error is not None else "ok",
        "total_findings": len(findings),
        "by_severity": _severity_counts(findings),
        "findings": findings,
        "explanation": explanation,
    }
    if metrics_error is not None:
        payload["metrics_error"] = str(metrics_error)
    return payload


@app.get("/api/overview")
def get_overview(hours: int = 24, period: str = "monthly"):
    # Resources
    raw_instances, resources_error = _collect_instances()
    if resources_error is not None:
        resources: Dict[str, Any] = {
            "status": "unavailable",
            "error": resources_error,
        }
        findings: List[Dict[str, Any]] = []
        insights: Dict[str, Any] = {"status": "unavailable"}
    else:
        by_state: Dict[str, int] = {}
        for instance in raw_instances:
            state = instance.get("State", {}).get("Name") or "unknown"
            by_state[state] = by_state.get(state, 0) + 1
        resources = {
            "status": "ok",
            "total_instances": len(raw_instances),
            "by_state": by_state,
        }

        instance_ids = [instance.get("InstanceId") for instance in raw_instances]
        metrics, metrics_error = _collect_metrics(instance_ids, None, hours)
        metrics_by_instance = {
            metric["instance_id"]: metric for metric in metrics if metric.get("instance_id")
        }
        findings = analyze_ec2_resources(
            raw_instances, metrics_by_instance=metrics_by_instance
        )
        insights = {
            "status": "ok",
            "metrics_status": "unavailable" if metrics_error is not None else "ok",
            "total_findings": len(findings),
            "by_severity": _severity_counts(findings),
        }

    # Cost
    try:
        cost: Dict[str, Any] = get_cost_summary(period=period)
    except CostServiceError as error:
        cost = {"status": "unavailable", "error": str(error)}

    return {
        "resources": resources,
        "cost": cost,
        "insights": insights,
    }


@app.get("/api/recommendations")
def get_recommendations(region: Optional[str] = None):
    raw_instances, error_response = _collect_instances(region)
    if error_response is not None:
        return error_response

    findings = analyze_ec2_resources(raw_instances)
    recommendations = [_legacy_recommendation(finding) for finding in findings]

    return {
        "total_recommendations": len(recommendations),
        "recommendations": recommendations
    }


@app.post("/api/iac/analyze")
def analyze_iac(payload: Dict[str, Any] = Body(...)):
    """Analyze a Terraform plan (and optional metrics/Infracost).

    Body: ``{"plan": <terraform show -json>, "metrics": {address: {...}},
    "infracost": <infracost json>}``. Analysis is read-only; no change is
    ever applied.
    """
    plan = payload.get("plan")
    if plan is None:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "error": "A Terraform plan is required under 'plan'."},
        )

    try:
        plan_analysis = parse_plan(plan)
    except IaCPlanError as error:
        return JSONResponse(
            status_code=400, content={"status": "error", "error": str(error)}
        )

    infracost = payload.get("infracost")
    infracost_summary = (
        normalize_infracost(infracost) if infracost is not None else infracost_status()
    )
    # Accept either a mapping keyed by resource id or the list shape returned
    # by /api/metrics/ec2, and normalize before the rule engine reads CPU data.
    metrics_by_address = normalize_metrics(payload.get("metrics"))

    findings = analyze_iac_changes(
        plan_analysis["changes"],
        metrics_by_address=metrics_by_address,
        infracost=infracost_summary,
    )

    return {
        "status": "ok",
        "changes": plan_analysis["changes"],
        "infracost": infracost_summary,
        "total_findings": len(findings),
        "findings": findings,
        "explanation": explain_findings(findings),
    }
