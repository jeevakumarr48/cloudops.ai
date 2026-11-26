"""CloudOps AI backend API.

Read-only cloud intelligence: AWS operational data, cost data,
infrastructure-as-code changes, and deterministic rules are combined into
explainable recommendations. AI explains findings; it never decides and never
performs AWS actions.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aws_client import AWSAccessError, discover_ec2_instances
from core import config, http_security
from core.authz import require_operator
from routers import ai as ai_router
from routers import auth as auth_router
from routers import demo as demo_router
from routers import governance as governance_router
from routers import security as security_router
from routers import workspaces as workspaces_router
from services.ai_explainer import explain_findings
from services.aws_metrics import MetricsUnavailableError, get_ec2_metrics
from services.cost_service import (
    CostServiceError,
    get_cost_forecast,
    get_cost_summary,
)
from services.decision_engine import (
    analyze_ec2_resources,
    analyze_iac_changes,
    normalize_metrics,
)
from services.governance_common import summarize as summarize_findings
from services.iac_analyzer import (
    IaCPlanError,
    infracost_status,
    normalize_infracost,
    parse_plan,
)
from services.rds_discovery import RDSAccessError, discover_rds_instances
from services.rds_governance import evaluate_instance as evaluate_rds_instance
from services.s3_discovery import S3AccessError, discover_s3_buckets
from services.s3_governance import evaluate_bucket
from services.s3_governance import summarize as summarize_s3

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
    # Credentials are needed for the session cookie when the frontend runs on
    # a different local origin. Origins are an explicit list, never "*".
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
# Origin check, security headers, request ids and the error envelope.
http_security.install(app, _cors_origins)


# CloudWatch retains 1-hour datapoints for 455 days, but anything beyond 30
# days is outside what the dashboard uses; bounding the window also bounds
# the size of each GetMetricData request.
MAX_METRIC_HOURS = 720
HoursParam = Query(24, ge=1, le=MAX_METRIC_HOURS)

# Shared CDN cache lifetimes (seconds). Cost Explorer bills $0.01 per request
# and its data refreshes only a few times a day, so successful cost responses
# are cached at Vercel's edge as well as in process memory. EC2 inventory is
# cached briefly so one dashboard load does not repeat DescribeInstances.
COST_CDN_SECONDS = int(os.environ.get("CLOUDOPS_COST_CDN_SECONDS", "86400"))
INVENTORY_CDN_SECONDS = int(os.environ.get("CLOUDOPS_INVENTORY_CDN_SECONDS", "60"))


def _cdn_cache(response: Response, seconds: int) -> None:
    """Allow Vercel's CDN (not browsers) to reuse a successful response.

    Only when the live AWS endpoints are deliberately public
    (CLOUDOPS_PUBLIC_SECURITY_FINDINGS=true). Behind operator sign-in a shared
    CDN copy could be served to someone who is not signed in, so responses
    are private; Cost Explorer spend is still bounded by the database cache
    and monthly request cap in ``services/cost_store``.
    """
    if not config.public_security_findings():
        response.headers["Cache-Control"] = "private, no-store"
    elif seconds > 0:
        response.headers["Cache-Control"] = (
            "public, max-age=0, s-maxage=%d, stale-while-revalidate=300" % seconds
        )

app.include_router(auth_router.router)
app.include_router(workspaces_router.router)
app.include_router(governance_router.router)
app.include_router(ai_router.router)
app.include_router(security_router.router)
app.include_router(demo_router.router)


def _seconds_until_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((midnight - now).total_seconds()))


def _cost_cdn_seconds() -> int:
    """Cost data is cached at the edge until UTC midnight at the latest, so a
    new billing day or month is never served from yesterday's cache."""
    return min(COST_CDN_SECONDS, _seconds_until_utc_midnight())


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
) -> tuple[List[Dict[str, Any]], Optional[AWSAccessError]]:
    """Collect EC2 instances, returning the error (not a response) on failure."""
    try:
        return discover_ec2_instances(region), None
    except AWSAccessError as error:
        return [], error


def _collect_metrics(
    instance_ids: List[str], region: Optional[str], hours: int
) -> tuple[List[Dict[str, Any]], Optional[MetricsUnavailableError]]:
    try:
        return get_ec2_metrics(instance_ids, region_name=region, hours=hours), None
    except MetricsUnavailableError as error:
        return [], error


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


@app.get("/api/resources/ec2", dependencies=[Depends(require_operator)])
def get_ec2_resources(response: Response, region: Optional[str] = None):
    raw_instances, error = _collect_instances(region)
    if error is not None:
        return _unavailable(error)
    _cdn_cache(response, INVENTORY_CDN_SECONDS)

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


@app.get("/api/metrics/ec2", dependencies=[Depends(require_operator)])
def get_ec2_metrics_endpoint(
    response: Response, hours: int = HoursParam, region: Optional[str] = None
):
    raw_instances, error = _collect_instances(region)
    if error is not None:
        return _unavailable(error)

    instance_ids = [i for i in (instance.get("InstanceId") for instance in raw_instances) if i]
    metrics, metrics_error = _collect_metrics(instance_ids, region, hours)
    if metrics_error is not None:
        return _unavailable(metrics_error)
    _cdn_cache(response, INVENTORY_CDN_SECONDS)

    return {
        "total_instances": len(instance_ids),
        "period_hours": hours,
        "metrics": metrics,
    }


@app.get("/api/costs", dependencies=[Depends(require_operator)])
def get_costs(response: Response, period: str = "monthly", group_by_service: bool = True):
    try:
        result = get_cost_summary(period=period, group_by_service=group_by_service)
    except CostServiceError as error:
        return _unavailable(error)
    _cdn_cache(response, _cost_cdn_seconds())
    return result


@app.get("/api/costs/forecast", dependencies=[Depends(require_operator)])
def get_costs_forecast(response: Response, period: str = "monthly"):
    try:
        result = get_cost_forecast(period=period)
    except CostServiceError as error:
        return _unavailable(error)
    _cdn_cache(response, _cost_cdn_seconds())
    return result


@app.get("/api/insights", dependencies=[Depends(require_operator)])
def get_insights(response: Response, hours: int = HoursParam, region: Optional[str] = None):
    raw_instances, error = _collect_instances(region)
    if error is not None:
        return _unavailable(error)

    instance_ids = [i for i in (instance.get("InstanceId") for instance in raw_instances) if i]
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
    else:
        _cdn_cache(response, INVENTORY_CDN_SECONDS)
    return payload


@app.get("/api/overview", dependencies=[Depends(require_operator)])
def get_overview(response: Response, hours: int = HoursParam, period: str = "monthly"):
    # Resources
    raw_instances, resources_error = _collect_instances()
    if resources_error is not None:
        resources: Dict[str, Any] = {
            "status": "unavailable",
            "error": str(resources_error),
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

        instance_ids = [i for i in (instance.get("InstanceId") for instance in raw_instances) if i]
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

    if resources_error is None and cost.get("status") != "unavailable":
        _cdn_cache(response, INVENTORY_CDN_SECONDS)
    return {
        "resources": resources,
        "cost": cost,
        "insights": insights,
    }


@app.get("/api/recommendations", dependencies=[Depends(require_operator)])
def get_recommendations(response: Response, region: Optional[str] = None):
    raw_instances, error = _collect_instances(region)
    if error is not None:
        return _unavailable(error)
    _cdn_cache(response, INVENTORY_CDN_SECONDS)

    findings = analyze_ec2_resources(raw_instances)
    recommendations = [_legacy_recommendation(finding) for finding in findings]

    return {
        "total_recommendations": len(recommendations),
        "recommendations": recommendations
    }


def _s3_inventory(refresh: bool):
    try:
        return discover_s3_buckets(refresh=refresh), None
    except S3AccessError as error:
        return None, error


@app.get("/api/resources/s3", dependencies=[Depends(require_operator)])
def get_s3_resources(response: Response, refresh: bool = False):
    """Read-only S3 inventory with a governance summary per bucket.

    Each configuration check reports ``ok``, ``not_configured``,
    ``access_denied`` or ``error``; storage figures come only from CloudWatch
    and are ``null`` when AWS has no datapoint.
    """
    inventory, error = _s3_inventory(refresh)
    if error is not None:
        return _unavailable(error)
    account_bpa = inventory["account_public_access_block"]
    for bucket in inventory["buckets"]:
        summary = summarize_s3(evaluate_bucket(bucket, account_bpa))
        bucket["governance"] = {
            "findings": len(summary["findings"]),
            "by_severity": summary["by_severity"],
            "by_state": summary["by_state"],
        }
    # Never CDN-cached: access depends on who is asking.
    response.headers["Cache-Control"] = "private, no-store"
    return inventory


@app.get("/api/resources/s3/{bucket_name}/governance", dependencies=[Depends(require_operator)])
def get_s3_bucket_governance(bucket_name: str, refresh: bool = False):
    """Every S3 rule's evaluation for one bucket, with evidence."""
    inventory, error = _s3_inventory(refresh)
    if error is not None:
        return _unavailable(error)
    bucket = next((b for b in inventory["buckets"] if b["name"] == bucket_name), None)
    if bucket is None:
        return JSONResponse(
            status_code=404,
            content={"status": "not_found", "error": "Bucket not found in the scanned account."},
        )
    evaluations = evaluate_bucket(bucket, inventory["account_public_access_block"])
    summary = summarize_s3(evaluations)
    return {
        "status": "ok",
        "scanned_at": inventory["scanned_at"],
        "bucket": bucket,
        "account_public_access_block": inventory["account_public_access_block"],
        "evaluations": evaluations,
        "findings": summary["findings"],
        "by_severity": summary["by_severity"],
        "by_state": summary["by_state"],
    }


@app.get("/api/resources/rds", dependencies=[Depends(require_operator)])
def get_rds_resources(response: Response, region: Optional[str] = None, refresh: bool = False):
    """Read-only RDS inventory with 14-day metrics and a governance summary."""
    try:
        inventory = discover_rds_instances(region=region, refresh=refresh)
    except RDSAccessError as error:
        return _unavailable(error)
    for db in inventory["instances"]:
        summary = summarize_findings(evaluate_rds_instance(db))
        db["governance"] = {
            "findings": len(summary["findings"]),
            "by_severity": summary["by_severity"],
            "by_state": summary["by_state"],
        }
    response.headers["Cache-Control"] = "private, no-store"
    return inventory


@app.get("/api/resources/rds/{database_id}/governance", dependencies=[Depends(require_operator)])
def get_rds_governance(database_id: str, region: Optional[str] = None, refresh: bool = False):
    """Every RDS rule's evaluation for one database, with evidence."""
    try:
        inventory = discover_rds_instances(region=region, refresh=refresh)
    except RDSAccessError as error:
        return _unavailable(error)
    db = next((d for d in inventory["instances"] if d["identifier"] == database_id), None)
    if db is None:
        return JSONResponse(
            status_code=404,
            content={"status": "not_found", "error": "Database not found in the scanned region."},
        )
    evaluations = evaluate_rds_instance(db)
    summary = summarize_findings(evaluations)
    return {
        "status": "ok",
        "scanned_at": inventory["scanned_at"],
        "database": db,
        "evaluations": evaluations,
        "findings": summary["findings"],
        "by_severity": summary["by_severity"],
        "by_state": summary["by_state"],
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
