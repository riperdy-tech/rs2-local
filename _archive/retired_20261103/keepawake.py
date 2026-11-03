#!/usr/bin/env python3
"""Hold Windows awake (SYSTEM only) for the duration of a long batch / orchestrator run.

Asserts ES_SYSTEM_REQUIRED (NOT ES_DISPLAY_REQUIRED) so the machine never sleeps mid-run but the
MONITOR is still free to power off per the OS idle timeout (`powercfg monitor-timeout-ac`). This box
exposes NO S0/S3 standby state (only Hibernate — see `powercfg /a`), so a dark display does NOT enter
Connected Standby / the Desktop Activity Moderator, i.e. it does NOT throttle background apps — which
is why holding the display on is no longer needed. Sleep/hibernate are disabled at the scheme level
(standby/hibernate-timeout-ac 0); this request is a belt-and-suspenders safety net.

Launch in the background at batch start and kill the pid at teardown:
    python keepawake.py &            # remember $!
    ...                              # long work
    kill <pid>                       # releases the request
"""
import ctypes
import time

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001

try:
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    print("[keepawake] holding SYSTEM awake (display free to sleep) until killed", flush=True)
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    pass
finally:
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)  # release
