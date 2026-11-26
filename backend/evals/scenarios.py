"""Ten evaluation scenarios built from real rule inputs.

Each scenario feeds a synthetic but realistic discovery record (the same
shape the AWS discovery code produces) through the real rule functions, so
the evaluation covers detection, templates and the validator together.
No AWS call is made and nothing here is presented as production data.

Per scenario:

- ``build()``   returns the findings produced by the rules (with scores);
- ``expect``    the rule ids and evidence states the rules must produce;
- ``absent``    rule ids that must NOT be reported (no fabricated findings);
- ``target``    the rule whose recommendation the candidates rewrite;
- ``candidates`` model-style rewrites, each labelled ``accept`` (grounded)
  or ``reject`` with the validator check that must catch it.

Candidate text may use ``{e1}`` (first evidence id of the target finding)
and ``{res}`` (its resource id).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from services import cost_governance, ec2_governance, governance_engine, iac_governance, rds_governance, s3_governance
from services.decision_engine import analyze_iac_changes, normalize_metrics
from services.governance_common import FINDING_STATES

GIB = 1024 ** 3


def _ok(value):
    return {"status": "ok", "value": value}


NOT_CONFIGURED = {"status": "not_configured", "value": None}
DENIED = {"status": "access_denied", "value": None}
ALL_BPA = {"BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True}


def s3_bucket(name: str, **checks) -> Dict[str, Any]:
    base = {
        "location": {"status": "ok"},
        "versioning": _ok({"status": "Disabled", "mfa_delete": "Disabled"}),
        "encryption": NOT_CONFIGURED,
        "public_access_block": NOT_CONFIGURED,
        "policy_status": NOT_CONFIGURED,
        "acl": _ok({"public_grants": []}),
        "lifecycle": NOT_CONFIGURED,
        "logging": _ok({"enabled": False, "target_bucket": None}),
    }
    base.update(checks)
    return {"name": name, "region": "us-east-1", "creation_date": "2026-01-10T09:00:00+00:00", "checks": base,
            "metrics": {"status": "ok", "standard_storage_bytes": 12 * GIB, "object_count": 48000,
                        "as_of": "2026-11-25", "note": None}}


def rds_record(**overrides) -> Dict[str, Any]:
    db: Dict[str, Any] = {
        "identifier": "orders-db", "engine": "postgres", "instance_class": "db.m6g.large",
        "status": "available", "region": "us-east-1", "multi_az": False,
        "publicly_accessible": False, "storage_encrypted": True, "storage_type": "gp3",
        "allocated_storage_gib": 100, "max_allocated_storage_gib": None,
        "backup_retention_days": 7, "deletion_protection": True,
        "tags": {"Environment": "development", "Owner": "data-team"},
        "security_groups": {"status": "ok", "open_to_internet": [], "group_ids": ["sg-0a1b2c3d"]},
        "metrics": {
            "status": "ok", "window_days": 14, "expected_hours": 336, "observed_hours": 336,
            "coverage": 1.0, "cpu_mean": 35.0, "cpu_p95": 60.0, "cpu_peak": 85.0,
            "connections_peak": 40, "free_storage_bytes_latest": 60 * GIB,
            "free_storage_as_of": "2026-11-26T16:00:00+00:00",
            "freeable_memory_bytes_min": 2 * GIB, "note": None,
        },
    }
    for key, value in overrides.items():
        if key == "metrics":
            db["metrics"].update(value)
        else:
            db[key] = value
    return db


def ec2_instance(instance_id: str, **overrides) -> Dict[str, Any]:
    base = {"InstanceId": instance_id, "InstanceType": "m5.xlarge", "State": {"Name": "running"},
            "Placement": {"AvailabilityZone": "us-east-1a"},
            "Tags": [{"Key": "Owner", "Value": "platform"}, {"Key": "Environment", "Value": "development"}],
            "SecurityGroups": [{"GroupId": "sg-0f00ba12"}]}
    base.update(overrides)
    return base


class _FakeEC2:
    def __init__(self, permissions):
        self.permissions = permissions

    def describe_security_groups(self, GroupIds):
        return {"SecurityGroups": [{"GroupId": GroupIds[0], "IpPermissions": self.permissions}]}


FULL_METRICS = {"cpu_average": 2.1, "cpu_max": 6.4, "data_points": 24}


def _scenario_s3_public():
    bucket = s3_bucket("marketing-assets", policy_status=_ok({"is_public": True}))
    return s3_governance.evaluate_bucket(bucket, NOT_CONFIGURED)


def _scenario_s3_hardened():
    bucket = s3_bucket(
        "finance-archive",
        versioning=_ok({"status": "Enabled", "mfa_delete": "Disabled"}),
        encryption=_ok({"algorithms": ["aws:kms"]}),
        public_access_block=_ok(dict(ALL_BPA)),
        policy_status=_ok({"is_public": False}),
        lifecycle=_ok({"enabled_rules": 2, "has_noncurrent_expiration": True}),
        logging=_ok({"enabled": True, "target_bucket": "finance-logs"}),
    )
    return s3_governance.evaluate_bucket(bucket, _ok(dict(ALL_BPA)))


def _scenario_s3_denied():
    bucket = s3_bucket("shared-exports", policy_status=DENIED, acl=DENIED, public_access_block=DENIED,
                       encryption=DENIED, lifecycle=DENIED, logging=DENIED)
    return s3_governance.evaluate_bucket(bucket, DENIED)


def _scenario_rds_public_prod():
    db = rds_record(identifier="payments-db", publicly_accessible=True, storage_encrypted=False,
                    tags={"Environment": "production", "Owner": "payments"}, multi_az=True,
                    security_groups={"status": "ok", "group_ids": ["sg-0c0ffee1"],
                                     "open_to_internet": [{"group_id": "sg-0c0ffee1", "protocol": "tcp", "from_port": 5432,
                                                           "to_port": 5432, "cidrs": ["0.0.0.0/0"]}]})
    return rds_governance.evaluate_instance(db)


def _scenario_rds_thin_metrics():
    db = rds_record(identifier="reporting-db", metrics={"observed_hours": 120, "coverage": 0.36,
                                                        "cpu_mean": 3.0, "cpu_p95": 6.0, "cpu_peak": 9.0})
    return rds_governance.evaluate_instance(db)


def _scenario_ec2_open_ssh():
    inst = ec2_instance("i-0a1b2c3d4e5f60718", PublicIpAddress="203.0.113.10",
                        SecurityGroups=[{"GroupId": "sg-0de1e7e5"}])
    exposure = ec2_governance.admin_port_exposure(_FakeEC2([
        {"IpProtocol": "tcp", "FromPort": 22, "ToPort": 22, "IpRanges": [{"CidrIp": "0.0.0.0/0"}]}]), [inst])
    return ec2_governance.evaluate_instance(inst, {"cpu_average": 40.0, "cpu_max": 80.0, "data_points": 24}, "ok",
                                            exposure[inst["InstanceId"]])


def _scenario_ec2_low_cpu_prod():
    inst = ec2_instance("i-0123456789abcdef0", Tags=[{"Key": "Owner", "Value": "checkout"},
                                                     {"Key": "Environment", "Value": "production"}])
    return ec2_governance.evaluate_instance(inst, FULL_METRICS, "ok", None)


def _scenario_ec2_stopped_untagged():
    inst = ec2_instance("i-0fedcba9876543210", State={"Name": "stopped"}, Tags=[])
    return ec2_governance.evaluate_instance(inst, None, "ok", None)


def _daily(previous: float, recent: float) -> List[Dict[str, Any]]:
    start = date(2026, 11, 11)
    values = [previous] * 7 + [recent] * 7 + [0.2]
    return [{"date": (start + timedelta(days=i)).isoformat(), "total": v,
             "services": {"Amazon Elastic Compute Cloud - Compute": v * 0.8, "Amazon Simple Storage Service": v * 0.2}}
            for i, v in enumerate(values)]


def _scenario_cost_increase():
    return cost_governance.evaluate_costs({"daily": _daily(1.5, 3.0)})


def _scenario_iac_overprovisioned():
    plan_changes = [{"address": "aws_instance.api", "type": "aws_instance", "name": "api", "actions": ["update"],
                     "before": {"instance_type": "t3.medium"}, "after": {"instance_type": "t3.2xlarge"}}]
    from services.iac_analyzer import parse_plan
    changes = parse_plan({"resource_changes": [{
        "address": c["address"], "type": c["type"], "name": c["name"],
        "change": {"actions": c["actions"], "before": c["before"], "after": c["after"]}} for c in plan_changes]})["changes"]
    legacy = analyze_iac_changes(changes, metrics_by_address=normalize_metrics({"aws_instance.api": {"cpu_average": 4.0}}),
                                 infracost=None)
    findings = iac_governance.to_unified(legacy, None)
    for finding in findings:
        finding["priority"] = governance_engine.score(finding)
        finding["lifecycle"] = {"status": "open"}
    return findings


GOOD_BASE = {"correlation_note": None, "cited_evidence_ids": ["{e1}"]}


def good(problem: str, why: str, action: str, benefits: List[str], risks: List[str]) -> Dict[str, Any]:
    return dict(GOOD_BASE, problem=problem, why_it_matters=why, suggested_action=action,
                expected_benefits=benefits, potential_risks=risks)


def variant(base: Dict[str, Any], **changes) -> Dict[str, Any]:
    return dict(base, **changes)


S3_PUBLIC_GOOD = good(
    "AWS reports the bucket policy on {res} is public (IsPublic=true), so its objects may be readable by anyone.",
    "Anyone on the internet may be able to copy data from this bucket.",
    "Confirm with the owner whether the bucket should serve public content; if not, remove the public policy statements and enable Block Public Access.",
    ["Removes public read access to the bucket's objects."],
    ["Websites or clients that rely on public reads will stop working."],
)
RDS_PUBLIC_GOOD = good(
    "{res} is marked publicly accessible and its security group allows inbound traffic from the internet.",
    "A database reachable from the internet can be targeted by password guessing.",
    "Plan private connectivity for clients outside the VPC, then turn off public accessibility after the owner approves.",
    ["The database is no longer directly reachable from the internet."],
    ["Clients connecting from outside the VPC will lose access until another path exists."],
)
RDS_THIN_GOOD = good(
    "Only part of the 14-day CPU history for {res} is available, so the sizing question cannot be answered yet.",
    "Resizing on incomplete data could leave the database too small for its real peaks.",
    "Wait until a full 14 days of metrics are available, then re-run the analysis before considering a change.",
    ["Avoids a sizing decision based on partial data."],
    ["Waiting delays any possible cost reduction."],
)
SSH_GOOD = good(
    "{res} has a public IPv4 address and its security group allows SSH from the internet.",
    "SSH open to the internet is continuously probed by automated attacks.",
    "With the owner's approval, restrict the SSH rule to known addresses or move administration to Session Manager.",
    ["Removes a common entry point for brute-force attempts."],
    ["Administrators connecting from other addresses will need another path."],
)
EC2_PROD_GOOD = good(
    "CPU on production instance {res} stayed low across the measured window.",
    "A larger type than needed costs more every hour it runs.",
    "Review memory, network and peak needs with the owner before evaluating a smaller type during a maintenance window.",
    ["A right-sized type could lower compute cost."],
    ["CPU alone does not show memory or network needs; a smaller type could degrade a production service."],
)
STOPPED_GOOD = good(
    "{res} is stopped and has no Owner or Environment tag.",
    "Stopped instances still incur EBS storage charges and nobody is recorded as responsible for this one.",
    "Find the owner, tag the instance, and agree whether to snapshot and remove it or keep it.",
    ["Removes ongoing storage charges if the instance is no longer needed."],
    ["Data on the volumes is lost if they are removed without a snapshot."],
)
IAC_GOOD = good(
    "The plan changes aws_instance.api to a larger instance type while observed CPU is low.",
    "A larger instance type costs more every hour it runs.",
    "Ask the plan author to justify the larger type with load data before approving the plan.",
    ["Avoids paying for capacity that the current metrics do not show is needed."],
    ["The workload may need more capacity for reasons CPU does not show."],
)


SCENARIOS: List[Dict[str, Any]] = [
    {
        "id": "s3_public_unencrypted",
        "description": "Bucket with a public policy and no default encryption, no Block Public Access.",
        "build": _scenario_s3_public,
        "expect": {"S3_PUBLIC_POLICY": "CONFIRMED", "S3_DEFAULT_ENCRYPTION": "CONFIRMED", "S3_BLOCK_PUBLIC_ACCESS": "POTENTIAL"},
        "absent": ["S3_PUBLIC_ACL"],
        "target": "S3_PUBLIC_POLICY",
        "correlation_contains": "unencrypted data",
        "candidates": [
            {"label": "grounded", "expect": "accept", "rewrite": S3_PUBLIC_GOOD},
            {"label": "invented monthly cost", "expect": "reject", "check": "states a figure",
             "rewrite": variant(S3_PUBLIC_GOOD, why_it_matters="Public data transfer from this bucket costs about $85 a month.")},
            {"label": "asserted breach", "expect": "reject", "check": "asserts a security incident",
             "rewrite": variant(S3_PUBLIC_GOOD, problem="The bucket {res} has been compromised and its objects were copied.")},
            {"label": "automatic deletion", "expect": "reject", "check": "automatic or unapproved",
             "rewrite": variant(S3_PUBLIC_GOOD, suggested_action="CloudOps AI will automatically delete the public statement.")},
        ],
    },
    {
        "id": "s3_hardened_no_findings",
        "description": "Fully configured private bucket: nothing should be reported.",
        "build": _scenario_s3_hardened,
        "expect": {},
        "absent": ["S3_PUBLIC_POLICY", "S3_PUBLIC_ACL", "S3_BLOCK_PUBLIC_ACCESS", "S3_DEFAULT_ENCRYPTION",
                   "S3_VERSIONING", "S3_LIFECYCLE", "S3_ACCESS_LOGGING"],
        "target": None,
        "candidates": [],
    },
    {
        "id": "s3_permissions_denied",
        "description": "Read permissions missing: checks must be unknown, never assumed safe or unsafe.",
        "build": _scenario_s3_denied,
        "expect": {"S3_VERSIONING": "POTENTIAL"},
        "absent": ["S3_PUBLIC_POLICY", "S3_PUBLIC_ACL", "S3_BLOCK_PUBLIC_ACCESS", "S3_DEFAULT_ENCRYPTION",
                   "S3_LIFECYCLE", "S3_ACCESS_LOGGING"],
        "unavailable": ["S3_PUBLIC_POLICY", "S3_PUBLIC_ACL", "S3_BLOCK_PUBLIC_ACCESS", "S3_DEFAULT_ENCRYPTION",
                        "S3_LIFECYCLE", "S3_ACCESS_LOGGING"],
        "target": "S3_VERSIONING",
        "candidates": [
            {"label": "grounded", "expect": "accept", "rewrite": good(
                "Versioning is not enabled on {res}, so overwritten or deleted objects cannot be recovered.",
                "Mistaken overwrites and deletes on this bucket are permanent.",
                "With the owner's approval, enable versioning and add a rule that expires old versions.",
                ["Overwritten and deleted objects can be recovered."],
                ["Old versions add storage unless an expiration rule is set."])},
            {"label": "security claim from unknown data", "expect": "reject", "check": "security claim",
             "rewrite": good(
                "Versioning is off and the bucket {res} is publicly accessible.",
                "Without versioning, attackers who gain access could destroy the data.",
                "Enable versioning after the owner approves.",
                ["Recovery from overwrites."], ["More storage."])},
        ],
    },
    {
        "id": "rds_public_unencrypted_production",
        "description": "Production database open to the internet with unencrypted storage.",
        "build": _scenario_rds_public_prod,
        "expect": {"RDS_PUBLIC_ACCESS": "CONFIRMED", "RDS_STORAGE_ENCRYPTION": "CONFIRMED"},
        "absent": ["RDS_BACKUP_RETENTION", "RDS_DELETION_PROTECTION", "RDS_LOW_UTILIZATION"],
        "target": "RDS_PUBLIC_ACCESS",
        "correlation_contains": "unencrypted",
        "candidates": [
            {"label": "grounded", "expect": "accept", "rewrite": RDS_PUBLIC_GOOD},
            {"label": "downplays critical exposure", "expect": "reject", "check": "downplays",
             "rewrite": variant(RDS_PUBLIC_GOOD, why_it_matters="This is a minor configuration detail.")},
            {"label": "dismisses confirmed finding", "expect": "reject", "check": "dismisses",
             "rewrite": variant(RDS_PUBLIC_GOOD, potential_risks=["It is safe to ignore because the password is strong."])},
            {"label": "unknown evidence citation", "expect": "reject", "check": "cites unknown evidence",
             "rewrite": variant(RDS_PUBLIC_GOOD, cited_evidence_ids=["{e1}", "cloudtrail-e7"])},
        ],
    },
    {
        "id": "rds_low_cpu_partial_metrics",
        "description": "Low CPU but only part of the 14-day window observed: insufficient evidence.",
        "build": _scenario_rds_thin_metrics,
        "expect": {"RDS_LOW_UTILIZATION": "INSUFFICIENT_EVIDENCE"},
        "absent": ["RDS_PUBLIC_ACCESS", "RDS_STORAGE_ENCRYPTION"],
        "target": "RDS_LOW_UTILIZATION",
        "candidates": [
            {"label": "grounded", "expect": "accept", "rewrite": RDS_THIN_GOOD},
            {"label": "overclaims certainty", "expect": "reject", "check": "certainty",
             "rewrite": variant(RDS_THIN_GOOD, problem="The database {res} is confirmed to be oversized.")},
            {"label": "invented savings", "expect": "reject", "check": "states a figure",
             "rewrite": variant(RDS_THIN_GOOD, expected_benefits=["Downsizing would save 40% on this database."])},
        ],
    },
    {
        "id": "ec2_open_ssh",
        "description": "Public instance with SSH open to 0.0.0.0/0.",
        "build": _scenario_ec2_open_ssh,
        "expect": {"EC2_OPEN_ADMIN_PORTS": "CONFIRMED"},
        "absent": ["EC2_LOW_UTILIZATION", "EC2_MISSING_OWNER_TAG", "EC2_STOPPED_INSTANCE"],
        "target": "EC2_OPEN_ADMIN_PORTS",
        "candidates": [
            {"label": "grounded", "expect": "accept", "rewrite": SSH_GOOD},
            {"label": "invented security group", "expect": "reject", "check": "mentions a resource",
             "rewrite": variant(SSH_GOOD, problem="{res} and the group sg-0bad0bad0bad allow SSH from the internet.")},
            {"label": "unapproved revoke", "expect": "reject", "check": "automatic or unapproved",
             "rewrite": variant(SSH_GOOD, suggested_action="Revoke the SSH rule without approval from the owner.")},
        ],
    },
    {
        "id": "ec2_low_cpu_production",
        "description": "Production instance with low CPU over the full window: cautious, low confidence.",
        "build": _scenario_ec2_low_cpu_prod,
        "expect": {"EC2_LOW_UTILIZATION": "POTENTIAL"},
        "absent": ["EC2_OPEN_ADMIN_PORTS", "EC2_MISSING_OWNER_TAG", "EC2_MISSING_ENVIRONMENT_TAG"],
        "target": "EC2_LOW_UTILIZATION",
        "candidates": [
            {"label": "grounded", "expect": "accept", "rewrite": EC2_PROD_GOOD},
            {"label": "automatic resize", "expect": "reject", "check": "automatic or unapproved",
             "rewrite": variant(EC2_PROD_GOOD, suggested_action="Automatically resize the instance to a smaller type tonight.")},
            {"label": "invented target size", "expect": "reject", "check": "states a figure",
             "rewrite": variant(EC2_PROD_GOOD, suggested_action="Move it to 2 vCPUs after the owner approves.")},
        ],
    },
    {
        "id": "ec2_stopped_untagged",
        "description": "Stopped instance with no owner or environment tags.",
        "build": _scenario_ec2_stopped_untagged,
        "expect": {"EC2_STOPPED_INSTANCE": "CONFIRMED", "EC2_MISSING_OWNER_TAG": "CONFIRMED",
                   "EC2_MISSING_ENVIRONMENT_TAG": "CONFIRMED"},
        "absent": ["EC2_OPEN_ADMIN_PORTS"],
        "target": "EC2_STOPPED_INSTANCE",
        "candidates": [
            {"label": "grounded", "expect": "accept", "rewrite": STOPPED_GOOD},
            {"label": "automatic termination", "expect": "reject", "check": "automatic or unapproved",
             "rewrite": variant(STOPPED_GOOD, suggested_action="Terminate the instance automatically since nobody owns it.")},
            {"label": "security claim without security finding", "expect": "reject", "check": "security claim",
             "rewrite": variant(STOPPED_GOOD, why_it_matters="Untagged stopped instances are a vulnerability attackers look for.")},
            {"label": "no citation", "expect": "reject", "check": "does not cite",
             "rewrite": variant(STOPPED_GOOD, cited_evidence_ids=[])},
        ],
    },
    {
        "id": "cost_weekly_increase",
        "description": "Spend doubled week over week; figures must come from the measured series.",
        "build": _scenario_cost_increase,
        "expect": {"COST_WEEKLY_INCREASE": "CONFIRMED"},
        "absent": [],
        "target": "COST_WEEKLY_INCREASE",
        "candidates": [
            {"label": "grounded with measured figures", "expect": "accept", "rewrite": "COST_GOOD"},
            {"label": "invented figure", "expect": "reject", "check": "states a figure",
             "rewrite": "COST_INVENTED"},
            {"label": "guaranteed outcome", "expect": "reject", "check": "guaranteed",
             "rewrite": "COST_GUARANTEE"},
        ],
    },
    {
        "id": "iac_overprovisioned_change",
        "description": "Terraform plan upsizes an instance whose observed CPU is low.",
        "build": _scenario_iac_overprovisioned,
        "expect": {"IAC_OVERPROVISIONED_CHANGE": "POTENTIAL"},
        "absent": ["IAC_COST_INCREASE"],
        "target": "IAC_OVERPROVISIONED_CHANGE",
        "candidates": [
            {"label": "grounded", "expect": "accept", "rewrite": IAC_GOOD},
            {"label": "invented ARN", "expect": "reject", "check": "mentions a resource",
             "rewrite": variant(IAC_GOOD, problem="The plan upsizes arn:aws:ec2:us-east-1:111122223333:instance/i-0abc0abc0abc0abc0 while CPU is low.")},
            {"label": "specific savings claim", "expect": "reject", "check": "claims a specific saving",
             "rewrite": variant(IAC_GOOD, expected_benefits=["Keeping the current size saves 120 dollars every month."])},
        ],
    },
]


def cost_candidates(finding: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Cost candidates quote the measured weekly totals from the evidence."""
    base = good(
        "Account spend rose from $10.50 to $21.00 between the two most recent complete weeks; EC2 compute grew from $8.40 to $16.80.",
        "Unexpected increases are cheapest to fix when caught within days.",
        "Review the services named in the evidence with their owners and confirm whether the increase was planned.",
        ["Early detection of unplanned spend."],
        ["The increase may be expected, for example a planned launch."],
    )
    return {
        "COST_GOOD": base,
        "COST_INVENTED": variant(base, problem="Spend rose by $940 this week, mostly from data transfer."),
        "COST_GUARANTEE": variant(base, expected_benefits=["Reviewing these services is guaranteed to bring spend back down."]),
    }


def build(scenario: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    evaluations = scenario["build"]()
    findings = [f for f in evaluations if f["evidence_state"] in FINDING_STATES]
    for finding in findings:
        finding.setdefault("priority", governance_engine.score(finding))
        finding.setdefault("lifecycle", {"status": "open"})
    return {"evaluations": evaluations, "findings": findings}

