"""Deterministic RDS governance rules.

Utilization rules only judge a database when there are at least 14 days of
hourly CloudWatch data with 80% coverage; otherwise they return
INSUFFICIENT_EVIDENCE. CPU alone never triggers a downsizing finding for a
production database without the recommendation calling out memory,
connections, storage and availability. No rule estimates savings.
"""

from __future__ import annotations

from typing import Any, Dict, List

from services.governance_common import (
    CONFIRMED,
    INSUFFICIENT_EVIDENCE,
    NO_ISSUE,
    POTENTIAL,
    Evaluation,
    is_production,
    summarize,
)

__all__ = ["evaluate_instance", "summarize", "THRESHOLDS"]

# Documented thresholds (see README).
THRESHOLDS = {
    "min_metric_days": 14,
    "min_coverage": 0.8,
    "low_cpu_mean": 10.0,       # % mean of hourly averages
    "low_cpu_p95": 20.0,        # % 95th percentile of hourly averages
    "low_cpu_peak": 40.0,       # % highest hourly maximum
    "storage_critical_free": 0.10,
    "storage_warning_free": 0.20,
    "storage_oversized_free": 0.80,
    "storage_oversized_min_gib": 100,
    "recommended_backup_days": 7,
}
_GIB = 1024 ** 3


def _ev(db: Dict[str, Any], rule_id: str, category: str, title: str) -> Evaluation:
    return Evaluation("RDS", db["identifier"], db.get("region"), rule_id, category, title, "aws:rds")


def _env_text(db: Dict[str, Any]) -> str:
    prod = is_production(db.get("tags") or {})
    return {True: "tagged as production", False: "tagged as non-production", None: "has no environment tag"}[prod]


def _is_aurora(db: Dict[str, Any]) -> bool:
    return (db.get("engine") or "").startswith("aurora")


def _rule_public(db) -> Dict:
    ev = _ev(db, "RDS_PUBLIC_ACCESS", "SECURITY", "Database is publicly accessible")
    if not db["publicly_accessible"]:
        ev.cite("rds:DescribeDBInstances", "PubliclyAccessible is false.")
        return ev.result(NO_ISSUE)
    ev.cite("rds:DescribeDBInstances", "PubliclyAccessible is true, so the endpoint resolves to a public IP.")
    groups = db.get("security_groups") or {}
    steps = [
        "Confirm whether any client must reach this database from the internet.",
        "If not, set PubliclyAccessible to false (requires a modify during a maintenance window).",
        "Restrict security group inbound rules to known CIDRs or security groups.",
    ]
    if groups.get("status") != "ok":
        ev.cite("ec2:DescribeSecurityGroups", "Security group rules could not be read.")
        return ev.result(
            POTENTIAL, "HIGH",
            "The database has a public address; whether the network allows internet traffic could not be verified.",
            "Review the security groups and disable public accessibility unless required.",
            steps, confidence="medium",
            missing_information=["Grant ec2:DescribeSecurityGroups to verify network exposure."],
        )
    open_rules = groups.get("open_to_internet") or []
    if open_rules:
        for rule in open_rules:
            ev.cite(
                "ec2:DescribeSecurityGroups",
                "%s allows %s on ports %s-%s from %s." % (
                    rule["group_id"], "all protocols" if rule["protocol"] == "-1" else rule["protocol"],
                    rule["from_port"], rule["to_port"], ", ".join(rule["cidrs"]),
                ),
            )
        return ev.result(
            CONFIRMED, "CRITICAL",
            "The database is reachable from any internet address on its port.",
            "Remove internet-wide inbound rules and disable public accessibility unless strictly required.",
            steps, confidence="high",
        )
    ev.cite("ec2:DescribeSecurityGroups", "No inbound rule allows 0.0.0.0/0 or ::/0 on the database port.")
    return ev.result(
        POTENTIAL, "MEDIUM",
        "The database has a public address but its security groups do not currently allow internet-wide access. One rule change would expose it.",
        "Disable public accessibility unless clients outside the VPC need it.",
        steps, confidence="high",
    )


def _rule_encryption(db) -> Dict:
    ev = _ev(db, "RDS_STORAGE_ENCRYPTION", "SECURITY", "Storage is not encrypted")
    if db["storage_encrypted"]:
        ev.cite("rds:DescribeDBInstances", "StorageEncrypted is true.")
        return ev.result(NO_ISSUE)
    ev.cite("rds:DescribeDBInstances", "StorageEncrypted is false.")
    return ev.result(
        CONFIRMED, "HIGH",
        "Data, automated backups and snapshots for this database are stored unencrypted.",
        "Plan a migration to an encrypted copy; encryption cannot be enabled in place.",
        ["Take a manual snapshot.", "Copy the snapshot with encryption enabled.",
         "Restore a new instance from the encrypted copy and cut over during a maintenance window."],
    )


def _rule_backups(db) -> Dict:
    ev = _ev(db, "RDS_BACKUP_RETENTION", "AVAILABILITY", "Automated backups are disabled or short")
    days = db.get("backup_retention_days")
    if days is None:
        ev.cite("rds:DescribeDBInstances", "Backup retention period was not returned.")
        return ev.result(INSUFFICIENT_EVIDENCE, "INFO", "Backup configuration could not be determined.", confidence="low")
    ev.cite("rds:DescribeDBInstances", "Backup retention period is %d day(s)." % days)
    ev.cite("rds:DescribeDBInstances", "The database %s." % _env_text(db))
    steps = ["Set the backup retention period to at least %d days." % THRESHOLDS["recommended_backup_days"],
             "Confirm the backup window does not overlap peak load."]
    if days == 0:
        return ev.result(
            CONFIRMED, "HIGH",
            "Automated backups are off, so point-in-time recovery is impossible.",
            "Enable automated backups.", steps,
        )
    if days < THRESHOLDS["recommended_backup_days"]:
        prod = is_production(db.get("tags") or {})
        return ev.result(
            POTENTIAL, "MEDIUM" if prod else "LOW",
            "Recovery is limited to the last %d day(s)." % days,
            "Increase retention to match your recovery needs.", steps,
            confidence="medium",
            missing_information=[] if prod is not None else ["Environment tag, to judge how critical recovery is."],
        )
    return ev.result(NO_ISSUE)


def _rule_multi_az(db) -> Dict:
    ev = _ev(db, "RDS_MULTI_AZ", "AVAILABILITY", "Production database runs in a single Availability Zone")
    if _is_aurora(db):
        ev.cite("rds:DescribeDBInstances", "Engine is %s; availability is set at the cluster level." % db["engine"])
        return ev.result(
            INSUFFICIENT_EVIDENCE, "INFO",
            "Aurora availability depends on replicas in the cluster, which this scan does not read yet.",
            confidence="low", missing_information=["Aurora cluster membership (rds:DescribeDBClusters)."],
        )
    ev.cite("rds:DescribeDBInstances", "MultiAZ is %s." % str(db["multi_az"]).lower())
    if db["multi_az"]:
        return ev.result(NO_ISSUE)
    prod = is_production(db.get("tags") or {})
    ev.cite("rds:DescribeDBInstances", "The database %s." % _env_text(db))
    if prod is False:
        return ev.result(NO_ISSUE)
    if prod is None:
        return ev.result(
            INSUFFICIENT_EVIDENCE, "INFO",
            "Single-AZ is fine for development but risky for production; the environment is unknown.",
            "Add an Environment tag so availability can be judged.",
            confidence="low", missing_information=["Environment tag."],
        )
    return ev.result(
        POTENTIAL, "MEDIUM",
        "An Availability Zone outage or instance failure would cause downtime until recovery.",
        "Evaluate Multi-AZ for this production database; it roughly doubles instance cost, so weigh it against your uptime needs.",
        ["Confirm the availability target for this workload.",
         "If needed, enable Multi-AZ during a maintenance window."],
        confidence="medium",
    )


def _rule_deletion_protection(db) -> Dict:
    ev = _ev(db, "RDS_DELETION_PROTECTION", "GOVERNANCE", "Deletion protection is off")
    ev.cite("rds:DescribeDBInstances", "DeletionProtection is %s." % str(db["deletion_protection"]).lower())
    if db["deletion_protection"]:
        return ev.result(NO_ISSUE)
    prod = is_production(db.get("tags") or {})
    ev.cite("rds:DescribeDBInstances", "The database %s." % _env_text(db))
    if prod is False:
        return ev.result(NO_ISSUE)
    return ev.result(
        POTENTIAL, "MEDIUM" if prod else "LOW",
        "The database can be deleted by a single API call or console action.",
        "Enable deletion protection for databases that must not be removed accidentally.",
        ["Enable deletion protection (no downtime, no cost)."],
        confidence="high" if prod else "low",
        missing_information=[] if prod else ["Environment tag."],
    )


def _rule_utilization(db) -> Dict:
    ev = _ev(db, "RDS_LOW_UTILIZATION", "UTILIZATION", "Database may be overprovisioned")
    metrics = db.get("metrics") or {}
    if metrics.get("status") in ("access_denied", "error"):
        return ev.unavailable("CloudWatch metrics", metrics.get("status"), "cloudwatch:GetMetricData")
    if db.get("status") != "available":
        ev.cite("rds:DescribeDBInstances", "Instance status is %s." % db.get("status"))
        return ev.result(INSUFFICIENT_EVIDENCE, "INFO", "Utilization is only judged for running databases.", confidence="low")
    coverage = metrics.get("coverage") or 0
    observed = metrics.get("observed_hours") or 0
    ev.cite(
        "cloudwatch:AWS/RDS CPUUtilization",
        "%d of %d expected hourly datapoints in the last %d days (%.0f%% coverage)." % (
            observed, metrics.get("expected_hours") or 0, metrics.get("window_days") or 0, coverage * 100,
        ),
    )
    if metrics.get("window_days", 0) < THRESHOLDS["min_metric_days"] or coverage < THRESHOLDS["min_coverage"]:
        return ev.result(
            INSUFFICIENT_EVIDENCE, "INFO",
            "Not enough metric history to judge utilization; at least 14 days with 80% hourly coverage is required.",
            confidence="low", missing_information=["More CloudWatch history."],
        )
    mean, p95, peak = metrics.get("cpu_mean"), metrics.get("cpu_p95"), metrics.get("cpu_peak")
    ev.cite("cloudwatch:AWS/RDS CPUUtilization", "CPU mean %s%%, p95 %s%%, peak %s%%." % (mean, p95, peak))
    if metrics.get("connections_peak") is not None:
        ev.cite("cloudwatch:AWS/RDS DatabaseConnections", "Peak connections: %d." % metrics["connections_peak"])
    if metrics.get("freeable_memory_bytes_min") is not None:
        ev.cite("cloudwatch:AWS/RDS FreeableMemory", "Lowest freeable memory: %.2f GiB." % (metrics["freeable_memory_bytes_min"] / _GIB))
    low = (
        mean is not None and p95 is not None and peak is not None
        and mean < THRESHOLDS["low_cpu_mean"] and p95 < THRESHOLDS["low_cpu_p95"] and peak < THRESHOLDS["low_cpu_peak"]
    )
    if not low:
        return ev.result(NO_ISSUE)
    prod = is_production(db.get("tags") or {})
    ev.cite("rds:DescribeDBInstances", "Instance class %s; the database %s%s." % (
        db.get("instance_class"), _env_text(db), ", Multi-AZ" if db.get("multi_az") else ""))
    missing = [
        "Memory pressure relative to the instance's RAM (needs the class's memory size and buffer cache hit ratio).",
        "Storage IOPS and throughput needs, which also depend on instance class.",
        "Planned load changes and month-end or seasonal peaks beyond the 14-day window.",
    ]
    steps = [
        "Review memory, connection and IOPS headroom, not just CPU.",
        "If a smaller class fits, test it on a snapshot restore or in staging first.",
        "Resize during a maintenance window; with Multi-AZ the change fails over with brief downtime.",
    ]
    if prod:
        return ev.result(
            POTENTIAL, "LOW",
            "CPU has been low for 14 days, but this is a production database. CPU alone is not enough to resize it safely.",
            "Treat this as a review item: confirm memory, connections and IOPS headroom with the owning team before considering a smaller class.",
            steps, confidence="low", missing_information=missing,
        )
    return ev.result(
        POTENTIAL, "MEDIUM" if prod is False else "LOW",
        "CPU has stayed low for the whole observation window, so a smaller instance class may be sufficient.",
        "Evaluate a smaller instance class after checking memory and IOPS needs.",
        steps, confidence="medium" if prod is False else "low", missing_information=missing,
    )


def _rule_storage(db) -> Dict:
    ev = _ev(db, "RDS_STORAGE_HEADROOM", "STORAGE", "Storage headroom needs attention")
    metrics = db.get("metrics") or {}
    if metrics.get("status") in ("access_denied", "error"):
        return ev.unavailable("CloudWatch metrics", metrics.get("status"), "cloudwatch:GetMetricData")
    allocated = db.get("allocated_storage_gib")
    free = metrics.get("free_storage_bytes_latest")
    if _is_aurora(db):
        ev.cite("rds:DescribeDBInstances", "Aurora storage grows automatically.")
        return ev.result(NO_ISSUE)
    if not allocated or free is None:
        ev.cite("cloudwatch:AWS/RDS FreeStorageSpace", "Free storage or allocated size is unavailable.")
        return ev.result(INSUFFICIENT_EVIDENCE, "INFO", "Storage headroom could not be judged.", confidence="low",
                         missing_information=["FreeStorageSpace datapoints."])
    ratio = (free / _GIB) / allocated
    ev.cite("rds:DescribeDBInstances", "Allocated storage %d GiB (%s)." % (allocated, db.get("storage_type")))
    ev.cite("cloudwatch:AWS/RDS FreeStorageSpace", "Free storage %.1f GiB (%.0f%%) as of %s." % (
        free / _GIB, ratio * 100, metrics.get("free_storage_as_of")))
    autoscaling = (db.get("max_allocated_storage_gib") or 0) > allocated
    if autoscaling:
        ev.cite("rds:DescribeDBInstances", "Storage autoscaling up to %d GiB." % db["max_allocated_storage_gib"])
    if ratio < THRESHOLDS["storage_critical_free"]:
        return ev.result(
            CONFIRMED, "MEDIUM" if autoscaling else "HIGH",
            "Less than 10%% of storage is free.%s" % (" Autoscaling should add space, up to its limit." if autoscaling else " The database stops accepting writes when storage is full."),
            "Increase allocated storage or enable storage autoscaling, and review data growth.",
            ["Check recent growth of FreeStorageSpace.", "Increase storage or enable autoscaling with a sensible maximum."],
        )
    if ratio < THRESHOLDS["storage_warning_free"] and not autoscaling:
        return ev.result(
            POTENTIAL, "MEDIUM", "Less than 20% of storage is free and autoscaling is off.",
            "Enable storage autoscaling or plan a storage increase.",
            ["Enable storage autoscaling with a maximum that fits your budget."], confidence="medium",
        )
    if ratio > THRESHOLDS["storage_oversized_free"] and allocated >= THRESHOLDS["storage_oversized_min_gib"]:
        return ev.result(
            POTENTIAL, "LOW",
            "More than 80% of a large allocation is unused. RDS storage cannot be shrunk in place.",
            "Factor this into the next migration or rebuild; do not migrate only to reclaim storage without weighing the effort.",
            ["Estimate expected growth.", "If a rebuild is planned, size storage closer to need and enable autoscaling."],
            confidence="medium", missing_information=["Expected data growth."],
        )
    return ev.result(NO_ISSUE)


def _rule_storage_type(db) -> Dict:
    ev = _ev(db, "RDS_GP2_STORAGE", "COST", "Storage uses the previous-generation gp2 type")
    storage_type = db.get("storage_type")
    ev.cite("rds:DescribeDBInstances", "Storage type is %s." % storage_type)
    if storage_type != "gp2":
        return ev.result(NO_ISSUE)
    return ev.result(
        POTENTIAL, "LOW",
        "gp3 decouples IOPS from size and is usually priced lower per GB than gp2. The difference for this database is not calculated.",
        "Compare gp2 and gp3 pricing for this region and size, then consider modifying the storage type.",
        ["Check current IOPS use against gp3 baseline performance.",
         "Modify storage type to gp3 during a maintenance window (the change runs online but can take time)."],
        confidence="medium",
        missing_information=["Region-specific storage pricing for this database."],
    )


def evaluate_instance(db: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Evaluate every RDS rule for one discovery record."""
    return [
        _rule_public(db),
        _rule_encryption(db),
        _rule_backups(db),
        _rule_multi_az(db),
        _rule_deletion_protection(db),
        _rule_utilization(db),
        _rule_storage(db),
        _rule_storage_type(db),
    ]
