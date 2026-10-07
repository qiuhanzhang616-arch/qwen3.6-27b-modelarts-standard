# Qwen3.6 Public Cloud Deployment Handover Checklist

Date and operator: ____________________

| Identity and artifact | Recorded value |
|---|---|
| Region and project | |
| Resource pool and selected node | |
| Hardware and driver | |
| Service ID and deployment ID | |
| Deployment version | |
| Client invocation prefix | |
| Source image and ARM64 digest | |
| SWR image and digest | |
| Actual runtime package versions | |
| Weight revision and inventory | |
| Startup SHA256SUMS location | |
| Weight file system and source directory | |
| Runtime file system and source directory | |
| Logs and retention | |
| Owner and rollback responsibility | |

- [ ] One replica, one unit instance and eight A2 NPUs verified.
- [ ] Actual TP8 / DP1 and BF16 confirmed from runtime evidence.
- [ ] Context 262144 confirmed from runtime and model listing.
- [ ] All weight shards verified and receipt saved.
- [ ] Model mount read-only with platform local storage acceleration enabled.
- [ ] Runtime mount writable and uncached.
- [ ] Graceful shutdown enabled; effective timeout and command recorded.
- [ ] Automatic rebuild disabled and saved value rechecked.
- [ ] Startup, readiness and liveness probes saved.
- [ ] Intended private/public client route works with valid TLS.
- [ ] API key is authorized for the intended service; no key in the evidence files.
- [ ] Ordinary chat and multi-turn chat pass.
- [ ] Portuguese/Chinese text and SSE output pass.
- [ ] Default thinking returns reasoning and final content separately.
- [ ] At least 261000 input tokens accepted with correct response.
- [ ] Over-context request rejected.
- [ ] Missing-key request rejected on the ModelArts route.
- [ ] Post-test health is 200 and platform remains 1/1 ready.
- [ ] Stop/recovery drill performed, or clearly marked unperformed below.
- [ ] Rollback point and stopping procedure retained.
- [ ] No throughput or multi-user capacity claim is based only on smoke tests.

Effective timeout and shutdown limits: ____________________

Shutdown/recovery drill result: ____________________

Known limitations and open acceptance items: ____________________

Approval for non-production use: ____________________
