"""AWS service-access layer for CloudOps AI.

This module centralizes boto3 client creation and read-only AWS discovery
calls. For now it supports EC2 instance discovery only; it is intended to
grow into the single service-access layer for the platform.

Authentication is delegated entirely to boto3's default credential chain
(environment variables, shared credentials/config files, or IAM roles for
the running compute). No credentials are created, stored, logged, or passed
explicitly here.
"""

import boto3
from botocore.exceptions import BotoCoreError, ClientError

__all__ = [
    "AWSAccessError",
    "create_ec2_client",
    "create_cloudwatch_client",
    "create_cost_explorer_client",
    "discover_ec2_instances",
]

EC2_SERVICE_NAME = "ec2"
CLOUDWATCH_SERVICE_NAME = "cloudwatch"
COST_EXPLORER_SERVICE_NAME = "ce"
# Cost Explorer is a global service and is only served from us-east-1.
COST_EXPLORER_REGION = "us-east-1"


class AWSAccessError(RuntimeError):
    """Raised when an AWS API call cannot be completed."""


def create_ec2_client(region_name=None):
    """Create a boto3 EC2 client using the default credential chain.

    ``region_name`` is optional. When it is omitted, boto3 resolves the
    region the same way the existing backend does (environment/config
    defaults), so no authentication behaviour changes.
    """
    return boto3.client(EC2_SERVICE_NAME, region_name=region_name)


def discover_ec2_instances(region_name=None):
    """Return the raw EC2 instance data for the current account.

    Calls ``describe_instances`` (paginated) and flattens the response
    across reservations, returning a list of raw instance dictionaries.
    Each dictionary is exactly what the current backend consumes:
    ``InstanceId``, ``InstanceType``, ``State``, ``Placement``,
    ``LaunchTime`` and ``Tags``.

    Raises:
        AWSAccessError: if the EC2 API call fails.
    """
    instances = []
    try:
        ec2 = create_ec2_client(region_name)
        paginator = ec2.get_paginator("describe_instances")

        for page in paginator.paginate():
            for reservation in page.get("Reservations", []):
                instances.extend(reservation.get("Instances", []))
    except (ClientError, BotoCoreError) as error:
        raise AWSAccessError("Failed to retrieve EC2 instances") from error

    return instances


def create_cloudwatch_client(region_name=None):
    """Create a boto3 CloudWatch client using the default credential chain.

    Read-only usage only; this module never creates alarms or modifies
    CloudWatch state.
    """
    return boto3.client(CLOUDWATCH_SERVICE_NAME, region_name=region_name)


def create_cost_explorer_client(region_name=COST_EXPLORER_REGION):
    """Create a boto3 Cost Explorer client using the default credential chain.

    Cost Explorer is global and must be addressed via us-east-1.
    """
    return boto3.client(COST_EXPLORER_SERVICE_NAME, region_name=region_name)
