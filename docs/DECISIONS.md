# Design decisions

## One load, one calculation path

Load and validate the CSVs at startup. Keep the portfolio calculations in pure Python and share them between the FastAPI and CLI adapters. A database would add a second copy of results that can be recomputed from the inputs.

## Keep an audit trail for input quality

Normalize peril spelling and day-first dates. Exclude claims whose policy is missing and claims with negative paid amounts. Report each exclusion with a count and converted amount. A portfolio lists its own negative payments and the book-wide orphan total because orphans cannot be assigned to a portfolio.

Keep claims linked to the policy named by their identifier, even if the loss predates inception. Flag that case, overlapping terms, mixed currencies, and settled claims with a reserve. These flags call for review without silently reassigning or dropping rows.

## Use explicit calculation rules

Convert each monetary amount in its own currency. Apply the inception month rate to premium and the loss month rate to claims. Count the full annual premium for each term. Settled claims contribute paid amounts, open claims contribute paid plus reserved amounts, and withdrawn and declined claims count as claims with zero incurred loss.

Use null for a loss ratio when premium is zero and for a largest claim when the group has no claims. Rank by unrounded loss ratio, then incurred loss and portfolio ID. Round values at the API boundary.

## Verify through the public interfaces

Keep an OpenAPI snapshot and a reproducible CLI proof on synthetic input. The independent checker uses the standard library to recalculate CSV totals and compare them with the running API. Docker and the WSL wrapper use the same application entry points.
