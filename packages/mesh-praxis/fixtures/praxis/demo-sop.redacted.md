# Praxis Demo Orders SOP

Operators may use `GET /orders` to inspect redacted order summaries during incident review.

Operators must not use `POST /orders/{order_id}/cancel` without Mesh connector certification,
an explicit Mesh approval record, and a visible rollback or reversal path.

Credential material is referenced by environment variable name only. Example authorization
headers are stored as `Authorization: REDACTED`.
