// Sample payloads shaped exactly like the FastAPI responses. Sample mode is the
// default so the console can be reviewed without AWS credentials; append
// ?sample=0 to reach a live backend. Every number here is invented for
// demonstration and the UI marks it as sample data - nothing in this file is
// ever presented as account data.

const instances = [
  { instance_id: 'i-0a91c4e7d2b5f3180', instance_type: 'm6i.2xlarge', state: 'running', availability_zone: 'us-east-1a', launch_time: '2026-08-14T09:12:00+00:00', tags: { Name: 'checkout-api', Environment: 'production', Owner: 'payments-team' } },
  { instance_id: 'i-04f2b8a1c9e7d6032', instance_type: 'm6i.2xlarge', state: 'running', availability_zone: 'us-east-1b', launch_time: '2026-08-14T09:40:00+00:00', tags: { Name: 'checkout-api', Environment: 'production', Owner: 'payments-team' } },
  { instance_id: 'i-07c5d3e2f8a1b4960', instance_type: 'c7g.xlarge', state: 'running', availability_zone: 'us-east-1a', launch_time: '2026-06-02T14:05:00+00:00', tags: { Name: 'search-worker', Environment: 'production', Owner: 'discovery-team' } },
  { instance_id: 'i-0b2e8f1a5d7c6941', instance_type: 'c7g.2xlarge', state: 'running', availability_zone: 'us-east-1b', launch_time: '2026-07-04T07:23:00+00:00', tags: { Name: 'search-indexer', Environment: 'production', Owner: 'discovery-team' } },
  { instance_id: 'i-0c9a3d6b1e4f8027', instance_type: 'r7g.2xlarge', state: 'running', availability_zone: 'us-east-1a', launch_time: '2026-05-11T22:08:00+00:00', tags: { Name: 'ledger-db-primary', Environment: 'production', Owner: 'finance-platform' } },
  { instance_id: 'i-0e6f1a9d4b7c2808', instance_type: 'r7g.large', state: 'running', availability_zone: 'us-east-1b', launch_time: '2026-03-19T11:47:00+00:00', tags: { Name: 'ledger-db-replica', Environment: 'production', Owner: 'finance-platform' } },
  { instance_id: 'i-0f34b7c2e5a8d1976', instance_type: 't3.small', state: 'running', availability_zone: 'us-east-1c', launch_time: '2026-01-08T07:31:00+00:00', tags: { Name: 'staging-jump', Environment: 'staging' } },
  { instance_id: 'i-0118b6e3f9a2c7058', instance_type: 'm7i.large', state: 'stopped', availability_zone: 'us-east-1b', launch_time: '2026-09-02T16:55:00+00:00', tags: { Name: 'analytics-canary', Environment: 'staging', Owner: 'analytics-team' } },
  { instance_id: 'i-0d18e7b4a2c9f5035', instance_type: 't3.medium', state: 'stopped', availability_zone: 'us-east-1a', launch_time: '2025-11-27T18:22:00+00:00', tags: { Name: 'reporting-batch', Environment: 'staging' } },
  { instance_id: 'i-03d7c2a8b6e1f9543', instance_type: 't4g.large', state: 'running', availability_zone: 'us-east-1c', launch_time: '2026-09-30T04:16:00+00:00', tags: { Name: 'event-relay', Environment: 'production' } },
]

// CloudWatch reports nothing for the stopped instances, so their rows stay
// em dashes - that is the unmeasured state the design has to carry well.
const metrics = [
  { instance_id: 'i-0a91c4e7d2b5f3180', cpu_average: 61.4, cpu_max: 88.2, data_points: 288 },
  { instance_id: 'i-04f2b8a1c9e7d6032', cpu_average: 58.9, cpu_max: 84.7, data_points: 288 },
  { instance_id: 'i-07c5d3e2f8a1b4960', cpu_average: 12.6, cpu_max: 31.5, data_points: 288 },
  { instance_id: 'i-0b2e8f1a5d7c6941', cpu_average: 3.8, cpu_max: 11.2, data_points: 288 },
  { instance_id: 'i-0c9a3d6b1e4f8027', cpu_average: 47.3, cpu_max: 79.6, data_points: 288 },
  { instance_id: 'i-0e6f1a9d4b7c2808', cpu_average: 44.1, cpu_max: 71.3, data_points: 288 },
  { instance_id: 'i-0f34b7c2e5a8d1976', cpu_average: 6.2, cpu_max: 24.9, data_points: 288 },
  { instance_id: 'i-03d7c2a8b6e1f9543', cpu_average: 68.7, cpu_max: 91.4, data_points: 288 },
]

// Cost Explorer returns total_cost as the sum of the grouped services, so the
// register, the chart and the service list agree. The rolling-30-day window
// contains month-to-date, so its total has to sit above it.
const costs = {
  status: 'ok',
  period: 'monthly',
  total_cost: 4281.36,
  currency: 'USD',
  start: '2026-10-01',
  end: '2026-10-25',
  end_inclusive: '2026-10-24',
  services: [
    { service: 'Amazon Elastic Compute Cloud', cost: 1902.44 },
    { service: 'Amazon Simple Storage Service', cost: 684.10 },
    { service: 'Amazon Relational Database Service', cost: 512.30 },
    { service: 'AWS Lambda', cost: 488.92 },
    { service: 'Amazon CloudWatch', cost: 297.14 },
    { service: 'Amazon Virtual Private Cloud', cost: 263.20 },
    { service: 'AWS Key Management Service', cost: 133.26 },
  ],
}

const dailyCosts = {
  status: 'ok',
  period: 'daily',
  total_cost: 5430.18,
  currency: 'USD',
  start: '2026-09-25',
  end: '2026-10-25',
  end_inclusive: '2026-10-24',
  services: [
    { service: 'Amazon Elastic Compute Cloud', cost: 2590.42 },
    { service: 'Amazon Simple Storage Service', cost: 862.18 },
    { service: 'Amazon Relational Database Service', cost: 631.55 },
    { service: 'AWS Lambda', cost: 542.30 },
    { service: 'Amazon CloudWatch', cost: 331.47 },
    { service: 'Amazon Virtual Private Cloud', cost: 289.16 },
    { service: 'Amazon DynamoDB', cost: 118.90 },
    { service: 'AWS Key Management Service', cost: 64.20 },
  ],
}

// AWS's own forecast for the full month, at roughly the month-to-date run rate.
const forecast = { available: true, mean: 5529.44, currency: 'USD', period: 'MONTHLY' }

const findings = [
  {
    resource_id: 'i-07c5d3e2f8a1b4960',
    resource_type: 'EC2',
    severity: 'high',
    issue: 'Underutilized instance, 24h CPU average 12.6%',
    recommendation: 'Review with the owning team and consider downsizing to c7g.large during the next maintenance window.',
    estimated_monthly_savings: 84.20,
    tags: { Name: 'search-worker', Environment: 'production', Owner: 'discovery-team' },
    evidence: ['Average CPUUtilization is 12.6% over the last 24 hours (288 datapoints).', 'Instance type c7g.xlarge is provisioned for sustained high utilization.'],
  },
  {
    resource_id: 'i-0b2e8f1a5d7c6941',
    resource_type: 'EC2',
    severity: 'medium',
    issue: 'Instance idle since launch, 24h CPU average 3.8%',
    recommendation: 'search-indexer has drawn under 12% of provisioned CPU since launch. Confirm the workload is still needed, then schedule a downsizing or a sunset date with the owning team.',
    estimated_monthly_savings: 176.40,
    tags: { Name: 'search-indexer', Environment: 'production', Owner: 'discovery-team' },
    evidence: ['Average CPUUtilization is 3.8% over the last 24 hours (288 datapoints).', 'Instance launched 2026-07-04 and has not reported sustained utilization above 12%.'],
  },
  {
    resource_id: 'i-0d18e7b4a2c9f5035',
    resource_type: 'EC2',
    severity: 'medium',
    issue: 'Stopped instance with no recent activity',
    recommendation: 'Confirm the reporting-batch workload is retired, then schedule termination with the owning team.',
    estimated_monthly_savings: 31.00,
    tags: { Name: 'reporting-batch', Environment: 'staging' },
    evidence: ['Instance state is stopped.', 'No CloudWatch datapoints returned in the last 24 hours.'],
  },
  {
    resource_id: 'i-0118b6e3f9a2c7058',
    resource_type: 'EC2',
    severity: 'medium',
    issue: 'Stopped instance with no recent activity',
    recommendation: 'analytics-canary has been stopped for over seven weeks. Either restart it behind a schedule or terminate it, so the inventory stops carrying a resource nobody measures.',
    estimated_monthly_savings: 48.50,
    tags: { Name: 'analytics-canary', Environment: 'staging', Owner: 'analytics-team' },
    evidence: ['Instance state is stopped.', 'No CloudWatch datapoints returned in the last 24 hours.'],
  },
  {
    resource_id: 'i-0f34b7c2e5a8d1976',
    resource_type: 'EC2',
    severity: 'low',
    issue: 'Missing ownership tag',
    recommendation: 'Assign an Owner tag so the resource has a responsible team.',
    estimated_monthly_savings: 0,
    tags: { Name: 'staging-jump', Environment: 'staging' },
    evidence: ['No Owner tag present on the resource.'],
  },
  {
    resource_id: 'i-03d7c2a8b6e1f9543',
    resource_type: 'EC2',
    severity: 'low',
    issue: 'Untagged resource discovered',
    recommendation: 'Add Environment and Owner tags to keep the inventory governable.',
    estimated_monthly_savings: 0,
    tags: {},
    evidence: ['Resource carries no tags.'],
  },
]

const byState = instances.reduce((tally, instance) => ({ ...tally, [instance.state]: (tally[instance.state] || 0) + 1 }), {})
const bySeverity = findings.reduce((tally, finding) => ({ ...tally, [finding.severity]: (tally[finding.severity] || 0) + 1 }), { high: 0, medium: 0, low: 0 })

export const sample = {
  overview: {
    status: 'ok',
    resources: { status: 'ok', total_instances: instances.length, by_state: byState },
    insights: { status: 'ok', metrics_status: 'ok', total_findings: findings.length, by_severity: bySeverity },
  },
  resources: {
    status: 'ok',
    total_instances: instances.length,
    instances,
  },
  metrics: {
    status: 'ok',
    total_instances: instances.length,
    period_hours: 24,
    metrics,
  },
  costs,
  // The rolling-30-day window carries its own grouped services: Cost Explorer
  // returns a service breakdown for every period, so the tab must render a
  // real chart rather than the empty frame.
  dailyCosts,
  forecast,
  insights: {
    status: 'ok',
    metrics_status: 'ok',
    total_findings: findings.length,
    by_severity: bySeverity,
    explanation: 'Six findings from the deterministic engine. One high-severity finding reports the largest saving; the rest are idle and stopped capacity plus tagging hygiene. Review each before acting: the engine proposes, it does not apply.',
    findings,
  },
}
