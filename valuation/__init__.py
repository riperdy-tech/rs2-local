"""valuation - the Phase-5 rebuild (SPEC_rebuild.md): classification, the three family engines and the discount rate
(sections 2-3), and `pit_data`, the one point-in-time data layer the engines, the priors and the validation harness all
import (Addenda A-D).

Nothing here imports a production valuation module, runs a model or reads a vendor snapshot. The engines read
point-in-time data through `common.CompanyPIT`, to be fed from `pit_data` (the adapter is the next integration step).
"""
