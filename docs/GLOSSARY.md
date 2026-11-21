# Loss experience

Terms for reporting how a book of insurance business has performed: which portfolios and perils lose money, and by how much. Code and docs use the English term; the Danish term is what source data and Danish colleagues may use.

## Book

**Asset**:
One insured property, identified by `asset_id`, belonging to exactly one Portfolio. The source also carries a region, a type, a construction year and a sum insured in DKK; nothing reads them, so they are not parsed.
_Danish_: aktiv, ejendom
_Avoid_: property, risk, location

**Portfolio**:
A book of Assets reported together, identified by `portfolio_id`. A Portfolio is not itself an Asset.
_Danish_: portefølje
_Avoid_: book (in code), account

**Policy**:
One policy term row: an Asset, a Peril, an inception and expiry date, an annual premium and the currency it was written in. Two terms of the same Asset and Peril are two Policies.
_Danish_: police
_Avoid_: contract, cover

**Claim**:
A loss reported against one Policy by `policy_id`, with a loss date, amounts paid and reserved, the currency they are recorded in, and a Claim status.
_Danish_: skade
_Avoid_: loss (on its own), event

**Peril**:
The cause a Policy covers. Closed set: `fire`, `flood`, `hail`, `storm`, `subsidence`. Source spellings differ in case and padding and are normalised at load.
_Danish_: fare
_Avoid_: risk type, line

**Claim status**:
Closed set: `settled`, `open`, `withdrawn`, `declined`.

## Results

**Earned premium**:
A Policy's full annual premium, converted to DKK at its inception month. No pro-rata. Field `earned_premium_dkk`.
_Danish_: optjent præmie

**Incurred loss**:
What a Claim has cost so far, in DKK at the loss month: `settled` is the amount paid; `open` is paid plus reserved; `withdrawn` and `declined` cost nothing. Field `incurred_loss_dkk`.
_Danish_: indtruffet skade
_Avoid_: ultimate, paid (alone)

**Loss ratio**:
Incurred loss divided by Earned premium, both in DKK, unitless. Field `loss_ratio`; `null` when Earned premium is zero.
_Danish_: skadeprocent

**Claim count**:
The number of Claims kept against the Policies counted, of every Claim status. A `withdrawn` or `declined` Claim counts as a Claim with an Incurred loss of 0; an Exclusion does not count. Field `claim_count`.

**Largest claim**:
The largest single Incurred loss among the Claims counted, in DKK. Field `largest_claim_dkk`; `null` when no Claim was counted.

**Loss experience**:
The result for one Portfolio: for every Peril, `policy_count`, `earned_premium_dkk`, `incurred_loss_dkk`, `loss_ratio`, `claim_count` and `largest_claim_dkk`, plus the Exclusions that affected it.

**Exclusion**:
A source row left out of every result, with its `ExclusionReason` and its amount in DKK so the reader can see what the answer does not contain. Closed set of reasons: `policy_not_found`, `negative_paid_amount`.
_Avoid_: dropped, cleaned

**Repair**:
A source value changed at load into its canonical form and counted in the data-quality report: peril spelling, a `DD-MM-YYYY` date. A Repair never removes a row.

## Rules

- All monetary results are in DKK; every amount is converted in the currency its own row states, never the currency of a related row.
- A Claim belongs to the Policy its `policy_id` names. A Claim whose Policy does not exist is an Exclusion, never a Claim of some other Policy.
- Missing is not zero: a Peril with no Earned premium has `loss_ratio: null`; a Portfolio with no Claims has `largest_claim_dkk: null`. A `policy_count` of 0 is an observed zero.
- Every result carries the count and DKK amount of its Exclusions.
- Re-loading the same files gives the same results; nothing is appended or cached.
