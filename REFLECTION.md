# Reflection

## What assumptions did you make?

I used conventional `/login`, `/meters`, and `/hierarchy` routes with a
username/password form and JSON data responses as a starting contract. These
are explicitly unverified. The adapter retains a cookie-backed session and
uses server-side credentials rather than asking API consumers to authenticate
to the legacy portal.

## Which part was the most difficult, and how did you get unstuck?

The key difficulty is that a useful adapter depends on the portal's actual
network behavior, which cannot be inferred from the assignment text alone.
Rather than present guesses as findings, I isolated those assumptions in the
adapter and documented the protocol discovery still required.

## If you had another day, what would you improve?

I would inspect the portal through an authorized browser session, document
sanitized requests and payloads, then implement exact response models and
HTML parsing only where the observed protocol requires it. I would also add
mocked tests for login, session expiry, pagination, and malformed upstream
responses.

## What mistake did you make while solving this?

The initial temptation is to treat plausible route names and login fields as
facts. That would make a clean-looking but unreliable integration, so this
starter labels them as assumptions and fails clearly when the response is
not JSON.

## If you were reviewing your own submission, what would you criticise?

It is not yet a verified integration: the real portal protocol and data
normalization are missing, and no automated test suite is included. The
process-wide session is also only suitable for a simple single-user
deployment. The next submission step should be protocol discovery followed
by tests against sanitized fixtures and authorized read-only requests.
