"""Deterministic S3 governance rules.

Every rule is evaluated for every bucket and returns exactly one evidence
state, so "no issue", "could not check" and "not enough evidence" are always
distinguishable:

- ``CONFIRMED``             AWS data directly shows the condition
- ``POTENTIAL``             the condition may matter; human context needed
- ``INSUFFICIENT_EVIDENCE`` data was read but is not enough to decide
- ``NO_ISSUE``              the check passed
- ``DATA_UNAVAILABLE``      the data could not be read (permissions/errors)

No rule estimates savings: per-bucket cost is not available without paid
features, so ``potential_monthly_impact`` is always ``None`` here. Rules are
pure functions of the discovery record; no AWS calls are made.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.governance_common import (
    CONFIRMED,
    DATA_UNAVAILABLE,
    INSUFFICIENT_EVIDENCE,
    NO_ISSUE,
    POTENTIAL,
    Evaluation,
    summarize,
)

__all__ = [
    "CONFIRMED",
    "DATA_UNAVAILABLE",
    "INSUFFICIENT_EVIDENCE",
    "LIFECYCLE_SIZE_THRESHOLD_BYTES",
    "NO_ISSUE",
    "POTENTIAL",
    "evaluate_bucket",
    "summarize",
]

# Below 1 GiB of Standard storage a lifecycle policy changes the bill by at
# most a few cents a month, so its absence is not reported as a finding.
LIFECYCLE_SIZE_THRESHOLD_BYTES = 1024 ** 3

_BPA_FLAGS = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")


def _human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return "%.1f %s" % (size, unit) if unit != "B" else "%d B" % size
        size /= 1024
    return "%d B" % value


def _Evaluation(bucket: Dict[str, Any], rule_id: str, category: str, title: str) -> Evaluation:
    return Evaluation("S3", bucket["name"], bucket.get("region"), rule_id, category, title, "aws:s3")


def _check(bucket: Dict, name: str) -> Dict[str, Any]:
    return (bucket.get("checks") or {}).get(name) or {"status": "error", "value": None}


def _unavailable(evaluation: Evaluation, check_name: str, check: Dict, api: str) -> Dict[str, Any]:
    return evaluation.unavailable(check_name, check.get("status"), api)


def _effective_bpa(bucket: Dict, account_bpa: Optional[Dict]) -> Dict[str, Optional[bool]]:
    """Combine bucket and account Block Public Access. ``None`` = unknown."""
    bucket_check = _check(bucket, "public_access_block")
    account_check = account_bpa or {"status": "error", "value": None}
    effective: Dict[str, Optional[bool]] = {}
    for flag in _BPA_FLAGS:
        values = []
        for check in (bucket_check, account_check):
            if check.get("status") == "ok":
                values.append(bool(check["value"].get(flag)))
            elif check.get("status") == "not_configured":
                values.append(False)
            else:
                values.append(None)
        if any(value is True for value in values):
            effective[flag] = True
        elif all(value is False for value in values):
            effective[flag] = False
        else:
            effective[flag] = None
    return effective


def _rule_public_policy(bucket, effective) -> Dict:
    ev = _Evaluation(bucket, "S3_PUBLIC_POLICY", "SECURITY", "Bucket policy grants public access")
    check = _check(bucket, "policy_status")
    if check["status"] == "not_configured":
        ev.cite("s3:GetBucketPolicyStatus", "Bucket has no bucket policy.")
        return ev.result(NO_ISSUE)
    if check["status"] != "ok":
        return _unavailable(ev, "policy status", check, "s3:GetBucketPolicyStatus")
    if not check["value"]["is_public"]:
        ev.cite("s3:GetBucketPolicyStatus", "AWS reports the bucket policy is not public (IsPublic=false).")
        return ev.result(NO_ISSUE)
    ev.cite("s3:GetBucketPolicyStatus", "AWS reports the bucket policy is public (IsPublic=true).")
    steps = [
        "Confirm whether this bucket is meant to serve public content (for example a static website).",
        "If not, remove the public statements from the bucket policy.",
        "Enable all four S3 Block Public Access settings on the bucket.",
    ]
    if effective.get("RestrictPublicBuckets") is True:
        ev.cite("s3:GetPublicAccessBlock",
                "RestrictPublicBuckets is enabled, which limits the policy to AWS principals and authorized users in this account.")
        return ev.result(
            POTENTIAL, "MEDIUM",
            "The policy is written to be public, but Block Public Access currently restricts it. Removing that setting would expose the bucket.",
            "Remove the public statements so protection does not depend on one setting.",
            steps, confidence="high",
        )
    return ev.result(
        CONFIRMED, "CRITICAL",
        "Anyone on the internet may be able to access this bucket according to its policy.",
        "Review immediately and remove public access unless it is intentional.",
        steps, confidence="high",
        missing_information=["Whether public access is intentional."],
    )


def _rule_public_acl(bucket, effective) -> Dict:
    ev = _Evaluation(bucket, "S3_PUBLIC_ACL", "SECURITY", "Bucket ACL grants access to all users")
    check = _check(bucket, "acl")
    if check["status"] != "ok":
        return _unavailable(ev, "bucket ACL", check, "s3:GetBucketAcl")
    grants = check["value"]["public_grants"]
    if not grants:
        ev.cite("s3:GetBucketAcl", "No ACL grants to AllUsers or AuthenticatedUsers.")
        return ev.result(NO_ISSUE)
    ev.cite("s3:GetBucketAcl", "ACL grants %s to a public group." % ", ".join(grants))
    steps = [
        "Remove the AllUsers/AuthenticatedUsers grants from the bucket ACL.",
        "Set Object Ownership to 'Bucket owner enforced' to disable ACLs.",
    ]
    if effective.get("IgnorePublicAcls") is True:
        ev.cite("s3:GetPublicAccessBlock", "IgnorePublicAcls is enabled, so these grants are not honoured.")
        return ev.result(
            POTENTIAL, "LOW",
            "A public ACL exists but is currently ignored because of Block Public Access.",
            "Remove the public grants so protection does not depend on one setting.",
            steps,
        )
    return ev.result(
        CONFIRMED, "HIGH",
        "The bucket ACL makes the bucket accessible to everyone and nothing is overriding it.",
        "Remove the public ACL grants unless public access is intentional.",
        steps, missing_information=["Whether public access is intentional."],
    )


def _rule_bpa(bucket, effective, account_bpa) -> Dict:
    ev = _Evaluation(bucket, "S3_BLOCK_PUBLIC_ACCESS", "SECURITY", "Block Public Access is not fully enabled")
    bucket_check = _check(bucket, "public_access_block")
    for label, check in (("bucket", bucket_check), ("account", account_bpa or {"status": "error"})):
        if check.get("status") == "ok":
            disabled = [flag for flag in _BPA_FLAGS if not check["value"].get(flag)]
            ev.cite(
                "s3:GetPublicAccessBlock" if label == "bucket" else "s3control:GetPublicAccessBlock",
                "%s-level settings: %s." % (label.capitalize(), "all enabled" if not disabled else "disabled: " + ", ".join(disabled)),
            )
        elif check.get("status") == "not_configured":
            ev.cite(
                "s3:GetPublicAccessBlock" if label == "bucket" else "s3control:GetPublicAccessBlock",
                "No %s-level Block Public Access configuration." % label,
            )
    if all(effective.get(flag) is True for flag in _BPA_FLAGS):
        return ev.result(NO_ISSUE)
    if any(effective.get(flag) is None for flag in _BPA_FLAGS):
        if bucket_check.get("status") not in ("ok", "not_configured"):
            return _unavailable(ev, "bucket Block Public Access settings", bucket_check, "s3:GetBucketPublicAccessBlock")
        return _unavailable(ev, "account Block Public Access settings", account_bpa or {}, "s3:GetAccountPublicAccessBlock")
    off = [flag for flag in _BPA_FLAGS if effective.get(flag) is False]
    return ev.result(
        POTENTIAL, "MEDIUM",
        "With these settings off, a future policy or ACL change could make the bucket public.",
        "Enable all four Block Public Access settings unless the bucket must be public.",
        ["Check whether any application relies on public access to this bucket.",
         "Enable %s at the bucket or account level." % ", ".join(off)],
        confidence="medium",
        missing_information=["Whether public access is intentional (for example a static website)."],
    )


def _rule_encryption(bucket) -> Dict:
    ev = _Evaluation(bucket, "S3_DEFAULT_ENCRYPTION", "SECURITY", "Default encryption is not configured")
    check = _check(bucket, "encryption")
    if check["status"] == "ok" and check["value"]["algorithms"]:
        ev.cite("s3:GetBucketEncryption", "Default encryption: %s." % ", ".join(check["value"]["algorithms"]))
        return ev.result(NO_ISSUE)
    if check["status"] in ("not_configured", "ok"):
        ev.cite("s3:GetBucketEncryption", "No default server-side encryption rule is configured.")
        return ev.result(
            CONFIRMED, "MEDIUM",
            "New objects are not encrypted at rest by default.",
            "Enable default encryption (SSE-S3 has no extra charge).",
            ["Set default encryption to SSE-S3, or SSE-KMS if you need key-level control."],
        )
    return _unavailable(ev, "encryption configuration", check, "s3:GetEncryptionConfiguration")


def _rule_versioning(bucket) -> Dict:
    ev = _Evaluation(bucket, "S3_VERSIONING", "CONFIGURATION", "Versioning is not enabled")
    check = _check(bucket, "versioning")
    if check["status"] != "ok":
        return _unavailable(ev, "versioning", check, "s3:GetBucketVersioning")
    status = check["value"]["status"]
    ev.cite("s3:GetBucketVersioning", "Versioning status: %s." % status)
    if status == "Enabled":
        return ev.result(NO_ISSUE)
    description = (
        "Versioning was enabled and later suspended; new overwrites and deletes are not recoverable."
        if status == "Suspended"
        else "Overwritten or deleted objects cannot be recovered."
    )
    return ev.result(
        POTENTIAL, "LOW", description,
        "Enable versioning if this bucket holds data that cannot be recreated, together with a lifecycle rule that expires old versions.",
        ["Decide whether the data is reproducible.",
         "If not, enable versioning and add a noncurrent-version expiration rule to cap storage growth."],
        confidence="low",
        missing_information=["Whether the bucket's data can be recreated from another source."],
    )


def _rule_lifecycle(bucket) -> Dict:
    ev = _Evaluation(bucket, "S3_LIFECYCLE", "STORAGE", "No lifecycle policy for stored data")
    check = _check(bucket, "lifecycle")
    versioning = _check(bucket, "versioning")
    versioned = versioning.get("status") == "ok" and versioning["value"]["status"] == "Enabled"
    metrics = bucket.get("metrics") or {}
    size = metrics.get("standard_storage_bytes")

    if check["status"] not in ("ok", "not_configured"):
        return _unavailable(ev, "lifecycle configuration", check, "s3:GetLifecycleConfiguration")

    if size is not None:
        ev.cite("cloudwatch:AWS/S3 BucketSizeBytes",
                "Standard storage: %s (as of %s)." % (_human_bytes(size), metrics.get("as_of") or "latest datapoint"))
    else:
        ev.cite("cloudwatch:AWS/S3 BucketSizeBytes", metrics.get("note") or "Storage size is unavailable.")

    if check["status"] == "ok" and check["value"]["enabled_rules"] > 0:
        ev.cite("s3:GetLifecycleConfiguration", "%d enabled lifecycle rule(s)." % check["value"]["enabled_rules"])
        if versioned and not check["value"]["has_noncurrent_expiration"]:
            ev.cite("s3:GetBucketVersioning", "Versioning is enabled.")
            return ev.result(
                POTENTIAL, "LOW",
                "Versioning is on but no rule expires noncurrent versions, so old versions are kept indefinitely.",
                "Add a NoncurrentVersionExpiration rule sized to your recovery needs.",
                ["Pick how long old versions must be kept.", "Add a NoncurrentVersionExpiration action to a lifecycle rule."],
                confidence="medium",
                missing_information=["How much storage noncurrent versions use (needs S3 Inventory or Storage Lens, not enabled to stay at $0)."],
            )
        return ev.result(NO_ISSUE)

    ev.cite("s3:GetLifecycleConfiguration", "No enabled lifecycle rules.")
    missing = ["Object age distribution (needs S3 Inventory or Storage Lens, which are not used to stay within budget)."]
    if versioned:
        ev.cite("s3:GetBucketVersioning", "Versioning is enabled, so noncurrent versions are never expired.")
    if size is None:
        return ev.result(
            INSUFFICIENT_EVIDENCE, "INFO",
            "There is no lifecycle policy, but storage size is unknown, so the cost impact cannot be judged.",
            "Check the bucket's size in the S3 console before deciding on a lifecycle policy.",
            confidence="low", missing_information=["Current storage size.", *missing],
        )
    if size < LIFECYCLE_SIZE_THRESHOLD_BYTES and not versioned:
        return ev.result(NO_ISSUE)
    return ev.result(
        POTENTIAL, "LOW",
        "Data is retained in its original storage class indefinitely. A lifecycle rule could move or expire data that is no longer needed.",
        "Review object access patterns and add transition or expiration rules where data is no longer needed.",
        ["Identify prefixes holding logs, backups or temporary data.",
         "Add transitions (for example to Standard-IA or Glacier Instant Retrieval) or expirations for those prefixes.",
         "Account for minimum storage duration and retrieval charges before transitioning."],
        confidence="medium", missing_information=missing,
    )


def _rule_logging(bucket) -> Dict:
    ev = _Evaluation(bucket, "S3_ACCESS_LOGGING", "GOVERNANCE", "Server access logging is disabled")
    check = _check(bucket, "logging")
    if check["status"] != "ok":
        return _unavailable(ev, "logging configuration", check, "s3:GetBucketLogging")
    if check["value"]["enabled"]:
        ev.cite("s3:GetBucketLogging", "Access logs are delivered to %s." % (check["value"]["target_bucket"] or "a target bucket"))
        return ev.result(NO_ISSUE)
    ev.cite("s3:GetBucketLogging", "Server access logging is not enabled.")
    return ev.result(
        POTENTIAL, "LOW",
        "Requests to this bucket are not recorded, which limits investigation after an incident.",
        "Enable access logging for buckets holding sensitive or shared data.",
        ["Choose a separate log bucket in the same region.",
         "Enable server access logging, or CloudTrail data events for selected buckets.",
         "Add a lifecycle rule to the log bucket; logs are stored objects and are billed as storage."],
        confidence="low",
        missing_information=["Whether this bucket holds sensitive data."],
    )


def evaluate_bucket(bucket: Dict[str, Any], account_bpa: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """Evaluate every S3 rule for one bucket discovery record."""
    effective = _effective_bpa(bucket, account_bpa)
    evaluations = [
        _rule_public_policy(bucket, effective),
        _rule_public_acl(bucket, effective),
        _rule_bpa(bucket, effective, account_bpa),
        _rule_encryption(bucket),
        _rule_versioning(bucket),
        _rule_lifecycle(bucket),
        _rule_logging(bucket),
    ]
    return evaluations
