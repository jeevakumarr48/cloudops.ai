"""Deterministic recommendation templates.

Every recommendation can be produced without any AI provider. Templates only
restate facts from the evidence bundle; they never introduce numbers.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from services.recommendations.schema import EvidenceRef, Recommendation, ResourceRef, Savings

# why_it_matters, expected_benefits, potential_risks per rule.
RULE_TEXT: Dict[str, Dict[str, Any]] = {
    "S3_PUBLIC_POLICY": {
        "why": "Data in a publicly readable bucket can be copied by anyone, and exposure is often discovered by automated scanners within hours.",
        "benefits": ["Removes internet-wide access to the bucket's data.", "Reduces the chance of a data exposure incident."],
        "risks": ["Applications or websites that rely on public reads will break.", "Check CloudFront or other consumers before changing the policy."],
    },
    "S3_PUBLIC_ACL": {
        "why": "ACL grants to AllUsers make objects readable (or writable) by anyone and are easy to overlook because they are not part of the bucket policy.",
        "benefits": ["Closes an access path that is not visible in the bucket policy.", "Simplifies access control by disabling ACLs."],
        "risks": ["Legacy clients that depend on ACL-based access may stop working."],
    },
    "S3_BLOCK_PUBLIC_ACCESS": {
        "why": "Block Public Access is a guardrail: without it, one mistaken policy or ACL change can expose the bucket.",
        "benefits": ["Prevents future accidental public exposure.", "Makes intent explicit and auditable."],
        "risks": ["Intentionally public buckets (for example static websites) will stop serving public content."],
    },
    "S3_DEFAULT_ENCRYPTION": {
        "why": "Without default encryption, objects uploaded without an encryption header are stored unencrypted at rest.",
        "benefits": ["All new objects are encrypted at rest automatically.", "Helps meet common compliance baselines."],
        "risks": ["Existing objects are not re-encrypted by this change.", "SSE-KMS adds KMS request charges; SSE-S3 does not."],
    },
    "S3_VERSIONING": {
        "why": "Without versioning, an overwrite or delete is permanent, so mistakes or malicious changes cannot be undone.",
        "benefits": ["Allows recovery from accidental overwrites and deletes."],
        "risks": ["Every overwrite keeps the old version, which grows storage unless a lifecycle rule expires noncurrent versions."],
    },
    "S3_LIFECYCLE": {
        "why": "Without lifecycle rules, data stays in its original storage class indefinitely, even when it is rarely or never read.",
        "benefits": ["Storage cost can fall when old data moves to cheaper classes or expires.", "Retention becomes explicit instead of accidental."],
        "risks": ["Colder classes have minimum storage durations and retrieval charges.", "An expiration rule permanently deletes data after the set age."],
    },
    "S3_ACCESS_LOGGING": {
        "why": "Without access logs there is no record of who read or changed data, which limits incident investigation.",
        "benefits": ["Creates an audit trail for requests to the bucket."],
        "risks": ["Logs are stored objects and add storage cost; set a lifecycle rule on the log bucket."],
    },
    "RDS_PUBLIC_ACCESS": {
        "why": "A database reachable from the internet is exposed to password guessing and to any unpatched engine vulnerability.",
        "benefits": ["Removes direct internet reachability of the database."],
        "risks": ["Clients connecting from outside the VPC will lose access; plan a VPN, bastion or private connectivity first."],
    },
    "RDS_STORAGE_ENCRYPTION": {
        "why": "Unencrypted storage means data, backups and snapshots are readable if the underlying storage or a shared snapshot is exposed.",
        "benefits": ["Data, backups and snapshots become encrypted at rest."],
        "risks": ["Requires a snapshot-copy-restore migration and a cutover window.", "Endpoints change unless you rename instances during cutover."],
    },
    "RDS_BACKUP_RETENTION": {
        "why": "Automated backups enable point-in-time recovery; short or zero retention limits how far back you can recover from data loss.",
        "benefits": ["Point-in-time recovery over a longer window."],
        "risks": ["Backup storage beyond the free allowance is billed.", "Enabling backups from zero can cause a brief I/O pause on some engines."],
    },
    "RDS_MULTI_AZ": {
        "why": "A single-AZ database is unavailable during an instance or Availability Zone failure until it is recovered.",
        "benefits": ["Automatic failover to a standby in another Availability Zone."],
        "risks": ["Multi-AZ roughly doubles instance cost.", "Conversion causes a brief performance impact."],
    },
    "RDS_DELETION_PROTECTION": {
        "why": "Without deletion protection, a single API call or console action can delete the database.",
        "benefits": ["Prevents accidental deletion at no cost."],
        "risks": ["Intentional deletions need an extra step to disable protection first."],
    },
    "RDS_LOW_UTILIZATION": {
        "why": "Database instances bill by the hour whether or not their capacity is used; sustained low CPU can indicate a larger class than needed.",
        "benefits": ["A right-sized instance class can lower compute cost."],
        "risks": ["CPU does not capture memory, connections or I/O needs; undersizing can degrade performance.", "Resizing causes downtime or a failover."],
    },
    "RDS_STORAGE_HEADROOM": {
        "why": "A database that runs out of storage stops accepting writes; heavily unused allocated storage is paid for but cannot be shrunk in place.",
        "benefits": ["Avoids write outages from full storage, or avoids paying for unused space in future rebuilds."],
        "risks": ["Storage increases cannot be reversed in place.", "Autoscaling without a maximum can grow cost unexpectedly."],
    },
    "RDS_GP2_STORAGE": {
        "why": "gp2 ties performance to volume size; gp3 sets IOPS independently and is usually priced lower per GB.",
        "benefits": ["Performance and size can be tuned independently.", "Storage cost may fall, depending on region and size."],
        "risks": ["The modification can take time to complete.", "Workloads relying on gp2 burst credits should be checked against gp3 baselines."],
    },
    "EC2_OPEN_ADMIN_PORTS": {
        "why": "SSH and RDP open to the internet are continuously probed by automated attacks.",
        "benefits": ["Removes a common entry point for brute-force and exploit attempts."],
        "risks": ["Administrators connecting from changing IPs need another path such as Session Manager."],
    },
    "EC2_STOPPED_INSTANCE": {
        "why": "Stopped instances still incur EBS volume and Elastic IP charges, and forgotten instances accumulate cost and patch debt.",
        "benefits": ["Removes ongoing storage charges for unused instances.", "Reduces unmanaged inventory."],
        "risks": ["Data on the volumes is lost if removed without a snapshot.", "Someone may still rely on the instance."],
    },
    "EC2_LOW_UTILIZATION": {
        "why": "Instances bill by the second while running; sustained low CPU can indicate a larger type than needed or an instance that could run on a schedule.",
        "benefits": ["A smaller type or a schedule can lower compute cost."],
        "risks": ["CPU does not capture memory, network or disk needs.", "Changing type requires a stop/start."],
    },
    "EC2_MISSING_OWNER_TAG": {
        "why": "Without an owner, nobody can confirm whether the instance is needed or approve changes to it.",
        "benefits": ["Every finding on this resource has someone to route it to."],
        "risks": ["None significant; tagging does not affect the running instance."],
    },
    "EC2_MISSING_ENVIRONMENT_TAG": {
        "why": "Rules use the environment to judge risk; without it, recommendations stay conservative and cost-saving advice is weaker.",
        "benefits": ["Enables production-aware recommendations."],
        "risks": ["None significant; tagging does not affect the running instance."],
    },
    "COST_WEEKLY_INCREASE": {
        "why": "Unexpected spend increases are cheapest to fix when caught within days rather than at month end.",
        "benefits": ["Early detection of unplanned spend."],
        "risks": ["The increase may be expected (for example a planned launch); confirm before acting."],
    },
}
CATEGORY_TEXT = {
    "SECURITY": ("This affects who can access the resource or its data.", "Reduced exposure."),
    "COST": ("This affects how much the account spends.", "Lower or more predictable spend."),
    "UTILIZATION": ("This affects whether paid capacity is being used.", "Capacity that matches demand."),
    "STORAGE": ("This affects how stored data grows and what it costs.", "Controlled storage growth."),
    "AVAILABILITY": ("This affects whether the service survives failures.", "Better resilience."),
    "INFRASTRUCTURE": ("This affects a proposed infrastructure change.", "Reviewed, intentional changes."),
    "GOVERNANCE": ("This affects accountability and auditability.", "Clearer ownership and audit trails."),
    "CONFIGURATION": ("This affects how the resource is configured.", "Safer defaults."),
}

_CORRELATIONS = [
    ({"S3_PUBLIC_POLICY", "S3_DEFAULT_ENCRYPTION"}, "The bucket is public and has no default encryption, so any exposure affects unencrypted data."),
    ({"S3_PUBLIC_ACL", "S3_DEFAULT_ENCRYPTION"}, "The bucket has a public ACL and no default encryption, so any exposure affects unencrypted data."),
    ({"RDS_PUBLIC_ACCESS", "RDS_STORAGE_ENCRYPTION"}, "The database is publicly reachable and its storage is unencrypted; fix network exposure first, then plan the encryption migration."),
    ({"RDS_PUBLIC_ACCESS", "RDS_BACKUP_RETENTION"}, "The database is publicly reachable and has limited backups, so a compromise could not be fully recovered."),
    ({"S3_VERSIONING", "S3_LIFECYCLE"}, "Enable versioning together with a noncurrent-version expiration rule, so recovery does not cause unbounded storage growth."),
    ({"EC2_LOW_UTILIZATION", "EC2_MISSING_ENVIRONMENT_TAG"}, "The environment is unknown, so the sizing advice is deliberately cautious; tagging the instance would sharpen it."),
    ({"EC2_OPEN_ADMIN_PORTS", "EC2_MISSING_OWNER_TAG"}, "SSH/RDP is open and no owner is recorded, so nobody is accountable for closing it."),
]


def correlation_note(rule_id: str, related: List[Dict[str, Any]]) -> Optional[str]:
    rules = {rule_id} | {r["rule_id"] for r in related}
    notes = [text for pair, text in _CORRELATIONS if rule_id in pair and pair <= rules]
    if notes:
        return " ".join(notes)
    if related:
        return "This resource has %d other finding(s): %s." % (
            len(related), "; ".join("%s (%s)" % (r["title"], r["severity"]) for r in related[:4]))
    return None


def recommendation_id(finding_id: str, evidence_hash: str) -> str:
    return hashlib.sha256(("%s|%s" % (finding_id, evidence_hash)).encode("utf-8")).hexdigest()[:20]


def _savings(finding: Dict[str, Any]) -> Savings:
    """Savings are stated only when a rule attached a measured figure
    (``measured_savings_usd`` with its ``savings_basis``). No rule estimates
    savings from list prices, so today this is almost always unvalidated."""
    amount = finding.get("measured_savings_usd")
    if isinstance(amount, (int, float)) and amount > 0 and finding.get("savings_basis"):
        return Savings(validated=True, amount_usd_per_month=round(float(amount), 2), basis=finding["savings_basis"])
    return Savings()


def build(bundle: Dict[str, Any]) -> Recommendation:
    finding = bundle["finding"]
    text = RULE_TEXT.get(finding["rule_id"])
    category_why, category_benefit = CATEGORY_TEXT.get(finding["category"], CATEGORY_TEXT["CONFIGURATION"])
    problem = finding.get("description") or finding["title"]
    if finding["evidence_state"] == "INSUFFICIENT_EVIDENCE":
        problem = "Not enough evidence to decide. " + problem
    missing = list(finding.get("missing_information") or [])
    return Recommendation(
        recommendation_id=recommendation_id(finding["finding_id"], bundle["evidence_hash"]),
        finding_id=finding["finding_id"],
        rule_id=finding["rule_id"],
        title=finding["title"],
        resource=ResourceRef(**bundle["resource"]),
        problem=problem,
        evidence=[EvidenceRef(evidence_id=e["id"], source=e["source"], observation=e["observation"])
                  for e in bundle["evidence"]],
        why_it_matters=text["why"] if text else category_why,
        suggested_action=finding.get("recommendation") or "Review this finding with the resource owner.",
        expected_benefits=text["benefits"] if text else [category_benefit],
        potential_risks=text["risks"] if text else ["Confirm the change with the resource owner before acting."],
        estimated_savings=_savings(finding),
        confidence=finding.get("confidence") or "low",
        missing_information=missing[:8],
        severity=finding["severity"],
        category=finding["category"],
        evidence_state=finding["evidence_state"],
        priority_score=(finding.get("priority") or {}).get("score", 0.0),
        remediation_steps=list(finding.get("remediation_steps") or [])[:10],
        related_findings=[r["finding_id"] for r in bundle["related"]],
        correlation_note=correlation_note(finding["rule_id"], bundle["related"]),
        generator="rules",
        evidence_hash=bundle["evidence_hash"],
        validation={"passed": True, "violations": [], "checked": "template"},
    )
