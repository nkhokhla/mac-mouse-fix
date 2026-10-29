# Mac Mouse Fix MCP Events

This is an actual MCP Events server, using the webhook profile in OpenAI's guide
for protocol `2026-07-28`. It is not the built-in GitHub automation trigger.

GitHub Actions event → private Site `/api/ingest` → durable event/outbox storage →
signed MCP webhook → subscribed agent with GitHub access.

## Endpoints and scope

- Private service: https://mac-mouse-fix-mcp-events.candidmars19.chatgpt.site
- MCP endpoint: `/mcp` (`server/discover`, `events/list`, `events/subscribe`,
  `events/unsubscribe`, `tools/list`, `tools/call`).
- Event: `upstream_sync.attention`.
- Repository: `nkhokhla/mac-mouse-fix`; base `master`; head `automation/upstream-sync`.
- Covers PR #3 and future open, non-draft PRs with those same repository/ref facts.
- GitHub workflow completion captures bot-created PRs even when their ordinary
  PR events are suppressed. Human feedback and external branch updates also relay.
- Exact trusted callback hostname defaults to `connectors.api.openai.com`. A new
  client callback host must be explicitly configured in `CALLBACK_HOST_ALLOWLIST`.
  Redirects, arbitrary hosts, non-HTTPS URLs, credentials and custom ports are denied.

## Activation

1. Deploy the Site owner-private, with `capabilities: ["mcp"]` and R2 `BUCKET`.
   Keep it private: service ingress relies on Sites dispatch authentication.
2. Install/connect the private plugin created by Sites. Verify `events/list` lists
   `upstream_sync.attention`. Subscribe using the instructions in
   [AGENT_INSTRUCTIONS.md](AGENT_INSTRUCTIONS.md), with no PR number filter.
3. Put `relay/mcp-upstream-events.yml` at `.github/workflows/mcp-upstream-events.yml`
   and the relay Python script at `integrations/mcp-events/relay/relay.py` on master.
4. Configure repository variable `MCP_EVENTS_URL` with the private Site origin above.
   Configure repository Actions secret `MCP_EVENTS_SITE_TOKEN` with that Site's
   service access token (used only in the `OAI-Sites-Authorization` request header).
   Do not put the token in source, workflow inputs, ordinary variables, or chat.
5. Run **Relay upstream sync MCP events** using workflow_dispatch, PR number `3`.
   Verify a signed callback is accepted and the subscribed agent actually runs.
   Server/relay deployment alone is not an active agent subscription.

The GitHub connector cannot configure repository secrets; activation needs that
repository setting and a connected MCP Events-capable client. Do not generate a
new Site bypass token just to inspect access. Use an existing supported token;
create or rotate one only when the owner explicitly requests it.

## Delivery and operational behavior

- Subscriptions are persisted, scoped by authenticated Site user, event, canonical
  filter arguments and callback URL. They expire unless refreshed (default 24h,
  minimum 1m, maximum 7d). Secret rotation is verified and dual-signed for one hour.
- Standard Webhooks HMAC-SHA256 signs event ID, current timestamp and exact body.
  Callback verification must echo a fresh challenge before any event is delivered.
- The relay has bounded exponential retries for connection errors/HTTP 408, 429 and
  5xx. Failed deliveries remain in a durable outbox. Retry with
  `retry_sync_deliveries`, or rerun the relay job after fixing the cause.
- No subscribers is a visible HTTP 503, not a fake successful delivery.
- Event IDs stay stable within a workflow attempt; reruns have distinct IDs.
  At-least-once delivery can produce duplicates after a crash; the consumer must
  deduplicate. Work leases and completed-event records prevent repeated repairs.
- Events are emit-only (`cursor: null`): subscription gaps are not protocol replayed.
  workflow_dispatch provides an explicit current-state bootstrap for PR #3 or a
  later sync PR. Stored events/outbox records are private; monitor storage growth.
- HTTP 410 removes a subscription. HTTP 413 records a permanent rejected delivery;
  it is not retried. Check response status, not just the delivered-record count.
- Model runs occur only after events. There is no GitHub polling schedule or
  continuously running model in this integration.
- The server never executes PR code, calls a model, merges, publishes, or modifies
  GitHub. Agent behavior is defined separately in AGENT_INSTRUCTIONS.md.

## Verification

Run `node --test tests/*.test.mjs` and
`python3 -m unittest discover -s tests -p 'test_*.py'`.
Run `bash scripts/build.sh` and `node scripts/validate-artifact.mjs` before publishing.

References:
- https://developers.openai.com/plugins/build/mcp-events
- https://mastra.ai/blog/introducing-mcp-events
- https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows

The MCP Events extension is experimental. This implementation targets the OpenAI
webhook integration documented above, not every evolving draft delivery mode.
