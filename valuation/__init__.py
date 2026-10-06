"""valuation - the Phase-5 rebuild's classification, three engines and discount rate (SPEC_rebuild.md sections 2-3).

Nothing here imports a production valuation module, runs a model or reads a vendor snapshot. Point-in-time data comes through the
interface in `common` (CompanyPIT); the shared data layer (valuation/pit_data.py, built by the harness branch) is adapted to it at merge.
"""
