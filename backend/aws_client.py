"""AWS service-access layer for CloudOps AI.

This module centralizes boto3 client creation and read-only AWS discovery
calls. For now it supports EC2 instance discovery only; it is intended to
grow into the single service-access layer for the platform.

Authentication is delegated entirely to boto3's default credential chain
(environment variables, shared credentials/config files, or IAM roles for
the running compute). No credentials are created, stored, logged, or passed
explicitly here.
"""

import copy
import os
import threading
import time

from botocore.exceptions import BotoCoreError, ClientError

from core import aws_session

__all__ = [
    "AWSAccessError",
    "create_cloudwatch_client",
    "create_cost_explorer_client",
    "create_ec2_client",
    "discover_ec2_instances",
]

EC2_SERVICE_NAME = "ec2"
CLOUDWATCH_SERVICE_NAME = "cloudwatch"
COST_EXPLORER_SERVICE_NAME = "ce"
# Cost Explorer is a global service and is only served from us-east-1.
COST_EXPLORER_REGION = "us-east-1"


# One dashboard load reaches several endpoints that each need the instance
# list. A short cache makes that a single DescribeInstances call while keeping
# inventory fresh. Set CLOUDOPS_DISCOVERY_CACHE_SECONDS=0 to disable.
_DISCOVERY_TTL_SECONDS = int(os.environ.get("CLOUDOPS_DISCOVERY_CACHE_SECONDS", "60"))
_discovery_cache = {}
_discovery_lock = threading.Lock()


class AWSAccessError(RuntimeError):
    """Raised when an AWS API call cannot be completed."""


def create_ec2_client(region_name=None):
    """Create a boto3 EC2 client using the default credential chain.

    ``region_name`` is optional. When it is omitted, boto3 resolves the
    region the same way the existing backend does (environment/config
    defaults), so no authentication behaviour changes.
    """
    return aws_session.client(EC2_SERVICE_NAME, region_name=region_name)


def discover_ec2_instances(region_name=None):
    """Return the raw EC2 instance data for the current account.

    Calls ``describe_instances`` (paginated) and flattens the response
    across reservations, returning a list of raw instance dictionaries.
    Each dictionary is exactly what the current backend consumes:
    ``InstanceId``, ``InstanceType``, ``State``, ``Placement``,
    ``LaunchTime`` and ``Tags``.

    Results are cached per region for ``CLOUDOPS_DISCOVERY_CACHE_SECONDS``
    (default 60). Failures are never cached.

    Raises:
        AWSAccessError: if the EC2 API call fails.
    """
    now = time.time()
    with _discovery_lock:
        entry = _discovery_cache.get(region_name)
        if entry is not None and entry[0] > now:
            return copy.deepcopy(entry[1])

    instances = []
    try:
        ec2 = create_ec2_client(region_name)
        paginator = ec2.get_paginator("describe_instances")

        for page in paginator.paginate():
            for reservation in page.get("Reservations", []):
                instances.extend(reservation.get("Instances", []))
    except (ClientError, BotoCoreError) as error:
        raise AWSAccessError("Failed to retrieve EC2 instances") from error

    if _DISCOVERY_TTL_SECONDS > 0:
        with _discovery_lock:
            _discovery_cache[region_name] = (
                time.time() + _DISCOVERY_TTL_SECONDS, copy.deepcopy(instances)
            )
    return instances


def create_cloudwatch_client(region_name=None):
    """Create a boto3 CloudWatch client using the default credential chain.

    Read-only usage only; this module never creates alarms or modifies
    CloudWatch state.
    """
    return aws_session.client(CLOUDWATCH_SERVICE_NAME, region_name=region_name)


def create_cost_explorer_client(region_name=COST_EXPLORER_REGION):
    """Create a boto3 Cost Explorer client using the default credential chain.

    Cost Explorer is global and must be addressed via us-east-1.
    """
    return aws_session.client(COST_EXPLORER_SERVICE_NAME, region_name=region_name)
