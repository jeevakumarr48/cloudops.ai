"""Read-only S3 bucket discovery for CloudOps AI.

Each configuration check is recorded with an explicit status so callers can
tell "not configured" apart from "we were not allowed to look" and from an
API failure:

- ``ok``              the setting was read; see ``value``
- ``not_configured``  AWS confirmed the setting is absent
- ``access_denied``   the credentials lack permission for this check
- ``error``           the call failed for another reason

Storage size and object counts come only from the free daily CloudWatch
storage metrics. A missing datapoint is reported as ``None`` with a reason;
it is never treated as zero. Nothing here writes to AWS.

Cost note (checked 2026-11-27): S3 GET-class requests cost about $0.0004 per
1,000, and storage metrics are read with CloudWatch ``GetMetricStatistics``,
which is covered by the free tier of 1 million API requests a month, so a scan
of tens of buckets costs well under a cent. Results are cached in process.
"""

from __future__ import annotations

import copy
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from core import aws_session
from services.cloudwatch_stats import metric_series

__all__ = [
    "S3AccessError",
    "clear_cache",
    "discover_s3_buckets",
]

_DENIED_CODES = {
    "AccessDenied",
    "AccessDeniedException",
    "AllAccessDisabled",
    "UnauthorizedOperation",
    "InvalidAccessKeyId",
    "SignatureDoesNotMatch",
    "ExpiredToken",
}
_NOT_CONFIGURED_CODES = {
    "ServerSideEncryptionConfigurationNotFoundError",
    "NoSuchPublicAccessBlockConfiguration",
    "NoSuchBucketPolicy",
    "NoSuchLifecycleConfiguration",
}
_PUBLIC_GRANTEES = {
    "http://acs.amazonaws.com/groups/global/AllUsers",
    "http://acs.amazonaws.com/groups/global/AuthenticatedUsers",
}
_BPA_FLAGS = ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets")

_CACHE_TTL_SECONDS = int(os.environ.get("CLOUDOPS_S3_CACHE_SECONDS", "900"))
_MAX_WORKERS = 8
_BOTO_CONFIG = Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=5, read_timeout=15)

_REFRESH_COOLDOWN_SECONDS = 60
_cache: Dict[str, Tuple[float, Dict, float]] = {}
_cache_lock = threading.Lock()


class S3AccessError(RuntimeError):
    """Raised when the bucket list itself cannot be retrieved."""


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _client(service: str, region: Optional[str] = None):
    return aws_session.client(service, region_name=region, config=_BOTO_CONFIG)


def _check(call: Callable[[], Any], parse: Callable[[Any], Any]) -> Dict[str, Any]:
    """Run one read-only call and classify the outcome."""
    try:
        return {"status": "ok", "value": parse(call())}
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        if code in _NOT_CONFIGURED_CODES:
            return {"status": "not_configured", "value": None}
        if code in _DENIED_CODES:
            return {"status": "access_denied", "value": None}
        return {"status": "error", "value": None, "error_code": code or "Unknown"}
    except BotoCoreError:
        return {"status": "error", "value": None, "error_code": "ConnectionError"}


def _region_of(location: Optional[str]) -> str:
    # GetBucketLocation returns None/"" for us-east-1 and "EU" for legacy eu-west-1.
    if not location:
        return "us-east-1"
    if location == "EU":
        return "eu-west-1"
    return location


def _parse_encryption(response: Dict) -> Dict:
    rules = response.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
    algorithms = []
    bucket_key = False
    for rule in rules:
        default = rule.get("ApplyServerSideEncryptionByDefault", {})
        if default.get("SSEAlgorithm"):
            algorithms.append(default["SSEAlgorithm"])
        bucket_key = bucket_key or bool(rule.get("BucketKeyEnabled"))
    return {"algorithms": algorithms, "bucket_key_enabled": bucket_key}


def _parse_bpa(response: Dict) -> Dict:
    config = response.get("PublicAccessBlockConfiguration", {})
    return {flag: bool(config.get(flag)) for flag in _BPA_FLAGS}


def _parse_acl(response: Dict) -> Dict:
    public = sorted({
        grant.get("Permission", "")
        for grant in response.get("Grants", [])
        if grant.get("Grantee", {}).get("URI") in _PUBLIC_GRANTEES
    })
    return {"public_grants": public}


def _parse_lifecycle(response: Dict) -> Dict:
    rules = response.get("Rules", [])
    return {
        "rule_count": len(rules),
        "enabled_rules": sum(1 for rule in rules if rule.get("Status") == "Enabled"),
        "has_transitions": any(rule.get("Transitions") for rule in rules),
        "has_expiration": any(rule.get("Expiration") for rule in rules),
        "has_noncurrent_expiration": any(rule.get("NoncurrentVersionExpiration") for rule in rules),
    }


def _parse_logging(response: Dict) -> Dict:
    enabled = response.get("LoggingEnabled")
    return {"enabled": bool(enabled), "target_bucket": (enabled or {}).get("TargetBucket")}


def _storage_metrics(bucket: str, region: str) -> Dict[str, Any]:
    """Latest daily BucketSizeBytes (Standard) and NumberOfObjects.

    S3 publishes these once a day; the lookback is 3 days so a delayed
    datapoint is still found. Absence is reported, never zero-filled.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=3)

    result: Dict[str, Any] = {
        "status": "ok",
        "standard_storage_bytes": None,
        "object_count": None,
        "as_of": None,
        "note": None,
    }
    def dims(storage_type: str) -> List[Dict[str, str]]:
        return [
            {"Name": "BucketName", "Value": bucket},
            {"Name": "StorageType", "Value": storage_type},
        ]

    try:
        client = _client("cloudwatch", region)
        size = metric_series(
            client, "AWS/S3", "BucketSizeBytes", dims("StandardStorage"), ("Average",), 86400, start, end
        )["Average"]
        objects = metric_series(
            client, "AWS/S3", "NumberOfObjects", dims("AllStorageTypes"), ("Average",), 86400, start, end
        )["Average"]
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        result["status"] = "access_denied" if code in _DENIED_CODES else "error"
        result["note"] = "CloudWatch storage metrics could not be read."
        return result
    except BotoCoreError:
        result["status"] = "error"
        result["note"] = "CloudWatch storage metrics could not be read."
        return result

    # Series are newest first; report the latest datapoint of each metric.
    if size:
        result["standard_storage_bytes"] = int(size[0][1])
    if objects:
        result["object_count"] = int(objects[0][1])
    latest = size[0][0] if size else (objects[0][0] if objects else None)
    if latest is not None:
        result["as_of"] = latest.isoformat() if hasattr(latest, "isoformat") else str(latest)
    if result["standard_storage_bytes"] is None and result["object_count"] is None:
        result["status"] = "no_data"
        result["note"] = (
            "No storage datapoints in the last 3 days. New or empty buckets and "
            "non-Standard storage classes may not report here; this does not mean zero usage."
        )
    return result


def _inspect_bucket(raw: Dict) -> Dict[str, Any]:
    name = raw["Name"]
    s3 = _client("s3")
    location = _check(lambda: s3.get_bucket_location(Bucket=name), lambda r: r.get("LocationConstraint"))
    region = _region_of(location["value"]) if location["status"] == "ok" else raw.get("BucketRegion")
    regional = _client("s3", region) if region else s3

    bucket: Dict[str, Any] = {
        "name": name,
        "region": region,
        "creation_date": raw["CreationDate"].isoformat() if raw.get("CreationDate") else None,
        "checks": {
            "location": {"status": location["status"]},
            "versioning": _check(
                lambda: regional.get_bucket_versioning(Bucket=name),
                lambda r: {"status": r.get("Status") or "Disabled", "mfa_delete": r.get("MFADelete") or "Disabled"},
            ),
            "encryption": _check(lambda: regional.get_bucket_encryption(Bucket=name), _parse_encryption),
            "public_access_block": _check(lambda: regional.get_public_access_block(Bucket=name), _parse_bpa),
            "policy_status": _check(
                lambda: regional.get_bucket_policy_status(Bucket=name),
                lambda r: {"is_public": bool(r.get("PolicyStatus", {}).get("IsPublic"))},
            ),
            "acl": _check(lambda: regional.get_bucket_acl(Bucket=name), _parse_acl),
            "lifecycle": _check(lambda: regional.get_bucket_lifecycle_configuration(Bucket=name), _parse_lifecycle),
            "logging": _check(lambda: regional.get_bucket_logging(Bucket=name), _parse_logging),
        },
    }
    bucket["metrics"] = _storage_metrics(name, region) if region else {
        "status": "error", "standard_storage_bytes": None, "object_count": None,
        "as_of": None, "note": "Bucket region unknown.",
    }
    return bucket


def _account_public_access_block() -> Dict[str, Any]:
    try:
        account_id = _client("sts").get_caller_identity()["Account"]
    except (ClientError, BotoCoreError):
        return {"status": "error", "value": None, "error_code": "CallerIdentityUnavailable"}
    return _check(
        lambda: _client("s3control", "us-east-1").get_public_access_block(AccountId=account_id),
        _parse_bpa,
    )


def _list_buckets() -> List[Dict]:
    s3 = _client("s3")
    buckets: List[Dict] = []
    try:
        for page in s3.get_paginator("list_buckets").paginate():
            buckets.extend(page.get("Buckets", []))
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        if code in _DENIED_CODES:
            raise S3AccessError("S3 bucket listing is not permitted for the configured credentials.") from error
        raise S3AccessError("Failed to list S3 buckets.") from error
    except BotoCoreError as error:
        raise S3AccessError("Failed to reach Amazon S3.") from error
    return buckets


def discover_s3_buckets(refresh: bool = False) -> Dict[str, Any]:
    """Return every bucket with its configuration checks and storage metrics.

    Raises:
        S3AccessError: if the bucket list itself cannot be read. Individual
        check failures are reported per bucket instead of raising.
    """
    now = time.time()
    with _cache_lock:
        entry = _cache.get("all")
        # A manual refresh is honoured at most once a minute so the refresh
        # button cannot be used to generate unbounded AWS requests.
        fresh_enough = entry is not None and (
            entry[0] > now if not refresh else entry[2] > now - _REFRESH_COOLDOWN_SECONDS
        )
        if fresh_enough:
            return copy.deepcopy(entry[1])

    raw_buckets = _list_buckets()
    account_bpa = _account_public_access_block() if raw_buckets else {"status": "not_checked", "value": None}
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        buckets = list(pool.map(_inspect_bucket, raw_buckets))
    buckets.sort(key=lambda bucket: bucket["name"])

    result = {
        "status": "ok",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "total_buckets": len(buckets),
        "account_public_access_block": account_bpa,
        "buckets": buckets,
    }
    with _cache_lock:
        _cache["all"] = (time.time() + _CACHE_TTL_SECONDS, copy.deepcopy(result), time.time())
    return result
