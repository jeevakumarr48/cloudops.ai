"""CloudOps AI backend service layer.

Services are grouped by responsibility:

- ``aws_metrics``     read-only CloudWatch metric collection
- ``cost_service``    read-only Cost Explorer collection
- ``decision_engine`` deterministic rule-based findings (no AWS, no AI)
- ``ai_explainer``    turns structured findings into human-readable text
- ``iac_analyzer``    Terraform plan JSON + Infracost normalization

All AWS access is performed read-only through ``aws_client``.
"""
