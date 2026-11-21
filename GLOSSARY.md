# DSN Analytics

Business vocabulary for exploring monthly employment, payroll, and social protection declarations.

## Language

**Employer (employeur)**:
The employing organization to which the establishments in the demo belong.
_Avoid_: Establishment

**Establishment (etablissement)**:
A reporting unit belonging to the employer, used to group employment, remuneration, and contributions.
_Avoid_: Employer

**Employee (salarie)**:
A person employed under one or more contracts, who may have assignments in multiple establishments.
_Avoid_: Contract

**DSN (Declaration sociale nominative)**:
A monthly declaration transmitting employees' payroll and social protection information.

**Synthetic DSN data**:
Artificial employment and payroll records representing fictional employers and employees, not records copied from real declarations.
_Avoid_: Anonymized production data, real employee data

**Suggested DSN prompt**:
A maintainer-defined DSN analytics question offered to users as a starting point for an analysis.
_Avoid_: Saved analysis, saved result

**DSN result card**:
The presentation of one DSN analysis result with its metric, period, filters, and supporting query evidence. Switching its visualization does not change the underlying analysis.
_Avoid_: Suggested DSN prompt

**Month-end headcount (effectif en fin de mois)**:
The number of distinct employees with at least one contract active on the last calendar day of a month within the selected scope. Employees are counted once per establishment and deduplicated across establishments for an overall total, so establishment counts are not necessarily additive.
_Avoid_: Contract count, full-time equivalents, employees present at any time during the month

**Remuneration reference month**:
The month to which remuneration relates, irrespective of when it is paid or the declaration is submitted.
_Avoid_: Payment month, declaration-submission month

**Gross payroll (masse salariale brute)**:
The sum of gross remuneration attributed to a reference month within the selected scope, including later adjustments relating to that month.
_Avoid_: Net payroll, employer payroll cost

**Employee contributions (cotisations salariales)**:
Social contributions borne by employees and attributed to their contribution reference month.
_Avoid_: Employer contributions, charges

**Contribution reference month**:
The month to which a social contribution relates, irrespective of when it is paid or the declaration is submitted.
_Avoid_: Payment month, declaration-submission month

**Employer contributions (cotisations patronales)**:
Social contributions borne by employers and attributed to their contribution reference month.
_Avoid_: Employee contributions, charges

**Total social contributions**:
The explicitly labeled sum of employee and employer contributions for the same scope and contribution reference period.
_Avoid_: Charges

**Current corrected declaration**:
The latest accepted declaration version for an establishment and reporting month, superseding earlier versions rather than accumulating with them. This is a current view, not a reconstruction of what was known at a past date.
