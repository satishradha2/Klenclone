# Commercial pricing and quotation enforcement checkpoint

Date: 2026-09-22

Environment: controlled local staging at `127.0.0.1:18082`

Source rule: BizModo remains strictly read-only.

## Outcome

Commercial pricing is implemented as a non-posting operating control inside the
customer-quotation workflow. It is not a separate pricing calculator and it
cannot post inventory or accounting.

The current flow provides active customer price groups, customer assignments,
effective-dated price lists with SKU prices, maximum discount percentages,
effective-dated group or SKU promotions, independent approvals, quotation
pricing snapshots and controlled read/write APIs in the Sales Orders workspace.

## Enforcement completed in this checkpoint

- Quotation creation and revision recompute pricing in the domain service. A
  caller cannot bypass controls by supplying a forged or stale pricing decision.
- Once an approved price list activates commercial pricing, an unassigned
  customer cannot receive a quotation.
- The quotation date must resolve to exactly one approved price list for the
  assigned customer group.
- Every quoted SKU must exist on that price list and its unit price must match.
- Document discounts cannot exceed the approved list ceiling.
- A group promotion can extend the ceiling for the whole quotation. A SKU
  promotion extends it only for the eligible line value in a mixed quotation.
- Promotion approval requires an overlapping approved price list; SKU-specific
  promotions must reference an item on that list.
- Price lists and promotions retain maker-checker self-approval protection.
- Customer assignments and pricing SKUs are validated against the controlled
  active customer and product masters at the API boundary.
- Promotion-backed quotations return the promotion code so a permitted draft
  revision preserves the selected promotion instead of silently removing it.

## Safety boundary

All pricing records and quotation snapshots are target-side operational data.
The workflow does not modify BizModo, reserve stock, create an invoice, create a
journal, post accounting or enable production posting.

## Verification

Focused tests cover approved/expired price lists, exact prices, discount limits,
unassigned customers, independent approvals, overlapping lists, promotion
eligibility, mixed-SKU discount allocation, domain-layer bypass prevention,
master-data validation and the complete HTTP quotation path. The complete test
suite passes 255 tests with 1 existing external-integration skip; the JavaScript
suite passes 36 tests. The controlled preview was rebuilt and reported healthy
with both databases reachable and posting disabled. Browser verification
confirmed the versioned pricing frontend, the focused quotation drawer,
customer-sensitive pricing guidance, zero horizontal overflow and no console
errors or warnings.

## Remaining acceptance gates

- Named sales-maker and independent sales-manager UAT using representative
  customer groups and real commercial policies.
- Business sign-off on whether list prices are maintained per base UOM only or
  require separate sell-UOM price breaks in a future increment.
- Production activation, permanent posting and final cutover remain separately
  controlled and disabled.
