"""The backtest harness of registration d09bb4a4 (revision 16 against one structural candidate, code layer only).

Offline, no model, no consensus, no targets.  Built and checked before any return is computed; the metrics (run_look.py) run only
behind AUTHORISED_LOOK_<n>.txt.  Nothing here changes production code: the two revisions' reference code is imported, one
revision per process (arm_worker.py), from trees at fee17cf and ac68e25.
"""
