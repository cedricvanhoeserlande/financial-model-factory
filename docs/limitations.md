# Limitations

Model Factory is an experimental portfolio prototype. Its current limitations
are material:

- Natural-language requirements can be ambiguous, incomplete, or inconsistent.
- Generated packages can contain financial, accounting, or economic errors even
  when code executes and implemented checks pass.
- AI review can miss issues. A targeted repair can also break previously
  working logic, so the full validation gate runs again after every repair.
- The demonstrated scope is bounded; arbitrary, highly specialised, circular,
  transaction, tax, covenant, or industry-specific models are not guaranteed to
  work.
- Input stress tests assess defined driver changes, not every real-world
  outcome.
- Live API output can vary and incurs cost and latency.
- The restricted local Python runtime is designed to constrain generated
  packages for this prototype. It is not a hardened isolation boundary for
  deliberately hostile or otherwise untrusted code.
- Passing validation means technical checks passed. It does not mean the model
  is investment-grade, audit-ready, economically appropriate, or suitable for
  a decision without professional review.

Users remain responsible for assumptions, model scope, review, and decisions.
