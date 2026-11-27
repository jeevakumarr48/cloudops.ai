"""Copy-ready AWS CLI commands for each rule (shown to people, never run).

CloudOps has read-only AWS access and never executes these commands. They are
generated deterministically from the finding: the resource id and region come
from discovery, and anything that needs a human decision (a smaller instance
type, a retention period, an owner name) is left as an ``<UPPER_CASE>``
placeholder instead of being guessed.

Each plan has:

- ``impact``: ``read_only`` (diagnose only), ``safe`` (additive, no effect on
  traffic), ``disruptive`` (can break clients or cause downtime) or
  ``destructive`` (removes data or resources; cannot be undone).
- ``before``: commands to record the current state first.
- ``steps``: the change itself, each with its own ``impact``.
- ``verify``: a read-only command that confirms the change.
- ``undo``: how to reverse it, or ``None`` when it cannot be reversed.
"""

from __future__ import annotations

import re
import shlex
from typing import Any, Callable, Dict, List, Optional

NOTICE = ("CloudOps never runs these commands. Review them with the resource owner, "
          "replace every <PLACEHOLDER>, and run them yourself with your own credentials.")

_IMPACT_RANK = {"read_only": 0, "safe": 1, "disruptive": 2, "destructive": 3}
_PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z0-9_]*>")
_OPEN_PORT_RE = re.compile(r"\b(sg-[0-9a-f]{8,17}) allows (SSH|RDP) \(port (\d{1,5})\)")


def _q(value: Any) -> str:
    return shlex.quote(str(value))


def _region(finding: Dict[str, Any]) -> str:
    region = finding.get("region")
    if region and region != "global" and re.fullmatch(r"[a-z]{2}(-[a-z]+)+-\d", str(region)):
        return " --region %s" % region
    return ""


def _step(label: str, command: str, impact: str = "safe") -> Dict[str, str]:
    return {"label": label, "command": command, "impact": impact}


def _plan(summary: str, steps: List[Dict[str, str]], before: Optional[List[Dict[str, str]]] = None,
          verify: Optional[str] = None, undo: Optional[str] = None, notes: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"summary": summary, "before": before or [], "steps": steps, "verify": verify, "undo": undo,
            "notes": notes or []}


# --- S3 ---------------------------------------------------------------------

def _s3_bpa(f, r):
    b = _q(f["resource_id"])
    return _plan(
        "Turn on all four Block Public Access settings for the bucket.",
        [_step("Block public access", "aws s3api put-public-access-block --bucket %s%s \\\n"
               "  --public-access-block-configuration "
               "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" % (b, r),
               "disruptive")],
        before=[_step("Save the current setting", "aws s3api get-public-access-block --bucket %s%s" % (b, r), "read_only")],
        verify="aws s3api get-public-access-block --bucket %s%s" % (b, r),
        undo="aws s3api delete-public-access-block --bucket %s%s" % (b, r),
        notes=["Confirm nothing (for example a static website) needs public reads first."],
    )


def _s3_public_policy(f, r):
    b = _q(f["resource_id"])
    plan = _s3_bpa(f, r)
    plan["summary"] = ("Block public policies on the bucket. This overrides the public statement without "
                       "deleting the policy, so it is easy to reverse.")
    plan["before"].insert(0, _step("Back up the bucket policy",
                                   "aws s3api get-bucket-policy --bucket %s%s --query Policy --output text "
                                   "> bucket-policy-backup.json" % (b, r), "read_only"))
    plan["verify"] = "aws s3api get-bucket-policy-status --bucket %s%s" % (b, r)
    return plan


def _s3_public_acl(f, r):
    b = _q(f["resource_id"])
    return _plan(
        "Disable ACLs by enforcing bucket-owner object ownership, which removes the public ACL grants.",
        [_step("Disable ACLs", "aws s3api put-bucket-ownership-controls --bucket %s%s \\\n"
               "  --ownership-controls 'Rules=[{ObjectOwnership=BucketOwnerEnforced}]'" % (b, r), "disruptive")],
        before=[_step("Back up the ACL", "aws s3api get-bucket-acl --bucket %s%s > bucket-acl-backup.json" % (b, r),
                      "read_only")],
        verify="aws s3api get-bucket-ownership-controls --bucket %s%s" % (b, r),
        undo="aws s3api put-bucket-ownership-controls --bucket %s%s \\\n"
             "  --ownership-controls 'Rules=[{ObjectOwnership=ObjectWriter}]'" % (b, r),
    )


def _s3_encryption(f, r):
    b = _q(f["resource_id"])
    return _plan(
        "Turn on default SSE-S3 encryption for new objects. SSE-S3 has no extra charge.",
        [_step("Enable default encryption", "aws s3api put-bucket-encryption --bucket %s%s \\\n"
               "  --server-side-encryption-configuration "
               "'{\"Rules\":[{\"ApplyServerSideEncryptionByDefault\":{\"SSEAlgorithm\":\"AES256\"}}]}'" % (b, r))],
        verify="aws s3api get-bucket-encryption --bucket %s%s" % (b, r),
        undo="aws s3api delete-bucket-encryption --bucket %s%s" % (b, r),
        notes=["Existing objects stay as they are; only new uploads are encrypted by default."],
    )


def _s3_versioning(f, r):
    b = _q(f["resource_id"])
    return _plan(
        "Turn on versioning so overwrites and deletes can be recovered.",
        [_step("Enable versioning",
               "aws s3api put-bucket-versioning --bucket %s%s --versioning-configuration Status=Enabled" % (b, r))],
        verify="aws s3api get-bucket-versioning --bucket %s%s" % (b, r),
        undo="aws s3api put-bucket-versioning --bucket %s%s --versioning-configuration Status=Suspended" % (b, r),
        notes=["Versioning can be suspended later but not fully turned off.",
               "Add a lifecycle rule that expires old versions so storage does not grow without limit."],
    )


def _s3_lifecycle(f, r):
    b = _q(f["resource_id"])
    rule = ("cat > lifecycle.json <<'EOF'\n"
            "{\"Rules\": [{\"ID\": \"move-to-infrequent-access\", \"Status\": \"Enabled\", \"Filter\": {},\n"
            "  \"Transitions\": [{\"Days\": <DAYS_BEFORE_IA>, \"StorageClass\": \"STANDARD_IA\"}]}]}\n"
            "EOF")
    return _plan(
        "Add a lifecycle rule that moves objects to Standard-IA after an age you choose. It deletes nothing.",
        [_step("Write the rule to a local file", rule),
         _step("Apply the rule", "aws s3api put-bucket-lifecycle-configuration --bucket %s%s "
               "--lifecycle-configuration file://lifecycle.json" % (b, r))],
        before=[_step("Check for an existing configuration (an error means there is none)",
                      "aws s3api get-bucket-lifecycle-configuration --bucket %s%s" % (b, r), "read_only")],
        verify="aws s3api get-bucket-lifecycle-configuration --bucket %s%s" % (b, r),
        undo="aws s3api delete-bucket-lifecycle --bucket %s%s" % (b, r),
        notes=["Applying a configuration replaces any existing one.",
               "Standard-IA has a minimum storage duration and a retrieval charge; pick the age from how the data is read."],
    )


def _s3_logging(f, r):
    b = _q(f["resource_id"])
    return _plan(
        "Send server access logs to a separate log bucket.",
        [_step("Enable access logging", "aws s3api put-bucket-logging --bucket %s%s \\\n"
               "  --bucket-logging-status '{\"LoggingEnabled\":{\"TargetBucket\":\"<LOG_BUCKET>\","
               "\"TargetPrefix\":\"%s/\"}}'" % (b, r, f["resource_id"]))],
        verify="aws s3api get-bucket-logging --bucket %s%s" % (b, r),
        undo="aws s3api put-bucket-logging --bucket %s%s --bucket-logging-status '{}'" % (b, r),
        notes=["The log bucket must allow the logging.s3.amazonaws.com service principal to write to it.",
               "Logs are stored objects; give the log bucket its own expiration rule."],
    )


# --- RDS --------------------------------------------------------------------

def _rds_describe(db, r, query):
    return "aws rds describe-db-instances --db-instance-identifier %s%s --query 'DBInstances[0].%s'" % (db, r, query)


def _rds_public(f, r):
    db = _q(f["resource_id"])
    return _plan(
        "Make the database reachable only from inside its VPC.",
        [_step("Turn off public access", "aws rds modify-db-instance --db-instance-identifier %s%s \\\n"
               "  --no-publicly-accessible --apply-immediately" % (db, r), "disruptive")],
        verify=_rds_describe(db, r, "PubliclyAccessible"),
        undo="aws rds modify-db-instance --db-instance-identifier %s%s --publicly-accessible --apply-immediately" % (db, r),
        notes=["Set up a VPN, bastion or other private path for clients outside the VPC before running this."],
    )


def _rds_encryption(f, r):
    db = _q(f["resource_id"])
    snap = _q("%s-pre-encryption" % f["resource_id"])
    enc = _q("%s-pre-encryption-encrypted" % f["resource_id"])
    new = _q("%s-encrypted" % f["resource_id"])
    return _plan(
        "Encryption cannot be turned on in place. Copy a snapshot with encryption and restore it as a new instance. "
        "The original instance is left running.",
        [_step("Take a snapshot", "aws rds create-db-snapshot --db-instance-identifier %s%s "
               "--db-snapshot-identifier %s" % (db, r, snap)),
         _step("Wait for it", "aws rds wait db-snapshot-available --db-snapshot-identifier %s%s" % (snap, r), "read_only"),
         _step("Copy it with encryption", "aws rds copy-db-snapshot --source-db-snapshot-identifier %s%s \\\n"
               "  --target-db-snapshot-identifier %s --kms-key-id <KMS_KEY_ID>" % (snap, r, enc)),
         _step("Wait for the copy", "aws rds wait db-snapshot-available --db-snapshot-identifier %s%s" % (enc, r),
               "read_only"),
         _step("Restore as a new encrypted instance",
               "aws rds restore-db-instance-from-db-snapshot --db-instance-identifier %s%s \\\n"
               "  --db-snapshot-identifier %s --db-subnet-group-name <SUBNET_GROUP> "
               "--vpc-security-group-ids <SECURITY_GROUP_ID>" % (new, r, enc))],
        verify="aws rds describe-db-instances --db-instance-identifier %s%s --query 'DBInstances[0].StorageEncrypted'" % (new, r),
        undo=None,
        notes=["Writes made after the snapshot are not in the new instance; plan a cutover window.",
               "Point applications at the new endpoint, test, and only then retire the old instance yourself.",
               "The new instance and snapshots are billed while both copies exist."],
    )


def _rds_backups(f, r):
    db = _q(f["resource_id"])
    return _plan(
        "Set the automated backup retention period (1 to 35 days).",
        [_step("Set backup retention", "aws rds modify-db-instance --db-instance-identifier %s%s \\\n"
               "  --backup-retention-period <RETENTION_DAYS> --apply-immediately" % (db, r))],
        before=[_step("Record the current value", _rds_describe(db, r, "BackupRetentionPeriod"), "read_only")],
        verify=_rds_describe(db, r, "BackupRetentionPeriod"),
        undo="Run the same command with the value recorded before the change.",
        notes=["Turning backups on from zero can cause a short I/O pause on some engines."],
    )


def _rds_multi_az(f, r):
    db = _q(f["resource_id"])
    return _plan(
        "Add a standby in another Availability Zone. Without --apply-immediately it runs in the next maintenance window.",
        [_step("Turn on Multi-AZ", "aws rds modify-db-instance --db-instance-identifier %s%s --multi-az" % (db, r),
               "disruptive")],
        verify=_rds_describe(db, r, "MultiAZ"),
        undo="aws rds modify-db-instance --db-instance-identifier %s%s --no-multi-az" % (db, r),
        notes=["Multi-AZ roughly doubles the instance charge."],
    )


def _rds_deletion(f, r):
    db = _q(f["resource_id"])
    return _plan(
        "Turn on deletion protection. It has no cost and no effect on traffic.",
        [_step("Turn on deletion protection", "aws rds modify-db-instance --db-instance-identifier %s%s "
               "--deletion-protection --apply-immediately" % (db, r))],
        verify=_rds_describe(db, r, "DeletionProtection"),
        undo="aws rds modify-db-instance --db-instance-identifier %s%s --no-deletion-protection --apply-immediately" % (db, r),
    )


def _rds_resize(f, r):
    db = _q(f["resource_id"])
    return _plan(
        "Move to a smaller instance class in the next maintenance window.",
        [_step("Change the instance class", "aws rds modify-db-instance --db-instance-identifier %s%s "
               "--db-instance-class <SMALLER_INSTANCE_CLASS>" % (db, r), "disruptive")],
        before=[_step("Record the current class", _rds_describe(db, r, "DBInstanceClass"), "read_only")],
        verify=_rds_describe(db, r, "[DBInstanceClass,PendingModifiedValues]"),
        undo="Run the same command with the class recorded before the change.",
        notes=["Check memory, connections and I/O as well as CPU before choosing the class."],
    )


def _rds_storage(f, r):
    db = _q(f["resource_id"])
    return _plan(
        "Turn on storage autoscaling with an upper limit, so the database grows before it fills up.",
        [_step("Set a storage ceiling", "aws rds modify-db-instance --db-instance-identifier %s%s "
               "--max-allocated-storage <MAX_STORAGE_GIB> --apply-immediately" % (db, r))],
        before=[_step("Record current storage", _rds_describe(db, r, "[AllocatedStorage,MaxAllocatedStorage]"),
                      "read_only")],
        verify=_rds_describe(db, r, "MaxAllocatedStorage"),
        undo="Storage that has grown cannot be shrunk in place; only the ceiling can be changed.",
        notes=["If the finding is about unused storage instead, there is no in-place fix: allocated storage "
               "cannot be reduced without restoring into a new, smaller instance."],
    )


def _rds_gp3(f, r):
    db = _q(f["resource_id"])
    return _plan(
        "Change the storage type from gp2 to gp3.",
        [_step("Switch to gp3", "aws rds modify-db-instance --db-instance-identifier %s%s --storage-type gp3 "
               "--apply-immediately" % (db, r), "disruptive")],
        verify=_rds_describe(db, r, "[StorageType,PendingModifiedValues]"),
        undo="aws rds modify-db-instance --db-instance-identifier %s%s --storage-type gp2 --apply-immediately" % (db, r),
        notes=["The storage optimization can take hours; another storage change is blocked until it finishes."],
    )


# --- EC2 --------------------------------------------------------------------

def _ec2_ports(f, r):
    opened: List[tuple] = []
    for e in f.get("evidence") or []:
        for group, service, port in _OPEN_PORT_RE.findall(e.get("observation") or ""):
            if (group, port) not in [(g, p) for g, _, p in opened]:
                opened.append((group, service, port))
    if not opened:
        opened = [("<SECURITY_GROUP_ID>", "SSH", "22")]
    steps, before = [], []
    for group, service, port in opened:
        before.append(_step("Save %s's rules" % group, "aws ec2 describe-security-groups --group-ids %s%s "
                            "> %s-backup.json" % (group, r, group), "read_only"))
        steps.append(_step("Remove %s (port %s) from anywhere, IPv4" % (service, port),
                           "aws ec2 revoke-security-group-ingress --group-id %s%s --protocol tcp --port %s "
                           "--cidr 0.0.0.0/0" % (group, r, port), "disruptive"))
        steps.append(_step("Remove %s (port %s) from anywhere, IPv6 (an error means there was no IPv6 rule)" % (service, port),
                           "aws ec2 revoke-security-group-ingress --group-id %s%s \\\n"
                           "  --ip-permissions 'IpProtocol=tcp,FromPort=%s,ToPort=%s,Ipv6Ranges=[{CidrIpv6=::/0}]'"
                           % (group, r, port, port), "disruptive"))
        steps.append(_step("Optional: allow only your own network",
                           "aws ec2 authorize-security-group-ingress --group-id %s%s --protocol tcp --port %s "
                           "--cidr <YOUR_IP_RANGE>" % (group, r, port)))
    return _plan(
        "Remove the internet-wide SSH/RDP rules and, if needed, allow only your own address range.",
        steps, before=before,
        verify="aws ec2 describe-security-groups --group-ids %s%s --query 'SecurityGroups[].IpPermissions'"
               % (" ".join(sorted({g for g, _, _ in opened})), r),
        undo="Re-add a rule from the saved backup if access is lost.",
        notes=["Session Manager needs no inbound port at all and is often the simpler replacement."],
    )


def _ec2_stopped(f, r):
    i = _q(f["resource_id"])
    return _plan(
        "Keep a backup image, then terminate the instance once its owner confirms it is no longer needed.",
        [_step("Create a backup image", "aws ec2 create-image --instance-id %s%s --name %s --no-reboot"
               % (i, r, _q("%s-final-backup" % f["resource_id"]))),
         _step("Terminate the instance (permanent)", "aws ec2 terminate-instances --instance-ids %s%s" % (i, r),
               "destructive")],
        before=[_step("List attached volumes and addresses", "aws ec2 describe-instances --instance-ids %s%s "
                      "--query 'Reservations[].Instances[].[BlockDeviceMappings,PublicIpAddress]'" % (i, r), "read_only")],
        verify="aws ec2 describe-instances --instance-ids %s%s --query 'Reservations[].Instances[].State.Name'" % (i, r),
        undo=None,
        notes=["Termination cannot be undone. Only the backup image can bring the instance back.",
               "The backup image and its snapshots are billed while you keep them.",
               "Release any Elastic IP that was attached, or it keeps billing."],
    )


def _ec2_resize(f, r):
    i = _q(f["resource_id"])
    return _plan(
        "Stop the instance, change its type, and start it again.",
        [_step("Stop", "aws ec2 stop-instances --instance-ids %s%s" % (i, r), "disruptive"),
         _step("Wait until stopped", "aws ec2 wait instance-stopped --instance-ids %s%s" % (i, r), "read_only"),
         _step("Change the type", "aws ec2 modify-instance-attribute --instance-id %s%s "
               "--instance-type Value=<SMALLER_INSTANCE_TYPE>" % (i, r)),
         _step("Start", "aws ec2 start-instances --instance-ids %s%s" % (i, r))],
        before=[_step("Record the current type", "aws ec2 describe-instances --instance-ids %s%s "
                      "--query 'Reservations[].Instances[].InstanceType'" % (i, r), "read_only")],
        verify="aws ec2 describe-instances --instance-ids %s%s --query 'Reservations[].Instances[].[InstanceType,State.Name]'"
               % (i, r),
        undo="Repeat the steps with the type recorded before the change.",
        notes=["The public IP changes on stop/start unless the instance has an Elastic IP."],
    )


def _ec2_tag(key: str, placeholder: str):
    def plan(f, r):
        i = _q(f["resource_id"])
        return _plan(
            "Add the %s tag. Tagging does not affect the running instance." % key,
            [_step("Add the tag", "aws ec2 create-tags --resources %s%s --tags Key=%s,Value=%s" % (i, r, key, placeholder))],
            verify="aws ec2 describe-tags%s --filters Name=resource-id,Values=%s Name=key,Values=%s" % (r, i, key),
            undo="aws ec2 delete-tags --resources %s%s --tags Key=%s" % (i, r, key),
        )
    return plan


# --- Cost -------------------------------------------------------------------

def _cost_increase(f, r):
    return _plan(
        "Find which services drove the increase. This only reads data.",
        [_step("Spend by service, day by day", "aws ce get-cost-and-usage --granularity DAILY --metrics UnblendedCost \\\n"
               "  --time-period Start=<START_DATE>,End=<END_DATE> --group-by Type=DIMENSION,Key=SERVICE", "read_only")],
        notes=["Each Cost Explorer API request is billed (check current pricing); one request is enough here.",
               "Dates use YYYY-MM-DD and the end date is exclusive."],
    )


_BUILDERS: Dict[str, Callable[[Dict[str, Any], str], Dict[str, Any]]] = {
    "S3_PUBLIC_POLICY": _s3_public_policy,
    "S3_PUBLIC_ACL": _s3_public_acl,
    "S3_BLOCK_PUBLIC_ACCESS": _s3_bpa,
    "S3_DEFAULT_ENCRYPTION": _s3_encryption,
    "S3_VERSIONING": _s3_versioning,
    "S3_LIFECYCLE": _s3_lifecycle,
    "S3_ACCESS_LOGGING": _s3_logging,
    "RDS_PUBLIC_ACCESS": _rds_public,
    "RDS_STORAGE_ENCRYPTION": _rds_encryption,
    "RDS_BACKUP_RETENTION": _rds_backups,
    "RDS_MULTI_AZ": _rds_multi_az,
    "RDS_DELETION_PROTECTION": _rds_deletion,
    "RDS_LOW_UTILIZATION": _rds_resize,
    "RDS_STORAGE_HEADROOM": _rds_storage,
    "RDS_GP2_STORAGE": _rds_gp3,
    "EC2_OPEN_ADMIN_PORTS": _ec2_ports,
    "EC2_STOPPED_INSTANCE": _ec2_stopped,
    "EC2_LOW_UTILIZATION": _ec2_resize,
    "EC2_MISSING_OWNER_TAG": _ec2_tag("Owner", "<OWNER>"),
    "EC2_MISSING_ENVIRONMENT_TAG": _ec2_tag("Environment", "<ENVIRONMENT>"),
    "COST_WEEKLY_INCREASE": _cost_increase,
}


def supported_rules() -> List[str]:
    return sorted(_BUILDERS)


def fix_for(finding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the command plan for a finding, or None when the fix belongs
    elsewhere (Terraform changes) or there is not enough evidence to act."""
    builder = _BUILDERS.get(str(finding.get("rule_id")))
    if builder is None or finding.get("evidence_state") not in ("CONFIRMED", "POTENTIAL"):
        return None
    plan = builder(finding, _region(finding))
    commands = [s["command"] for s in plan["before"] + plan["steps"]] + [plan["verify"] or ""]
    placeholders = sorted({p for c in commands for p in _PLACEHOLDER_RE.findall(c)})
    impact = max((s["impact"] for s in plan["steps"]), key=_IMPACT_RANK.__getitem__)
    # A quick win is a single low-risk command: no migration, no downtime.
    quick = impact == "safe" and len(plan["steps"]) == 1
    return dict(plan, rule_id=finding["rule_id"], impact=impact, quick=quick, placeholders=placeholders,
                runs_automatically=False, notice=NOTICE)
