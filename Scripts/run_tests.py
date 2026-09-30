"""Run unittest suites and write results to a log file (no stderr noise)."""
import faulthandler
import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# If a suite deadlocks, dump every thread's stack instead of hanging forever.
FAULTHANDLER = int(os.getenv("TEST_FAULTHANDLER_SECONDS", "0"))
if FAULTHANDLER:
    faulthandler.dump_traceback_later(FAULTHANDLER, exit=True)

out = io.StringIO()
suite = unittest.TestLoader().loadTestsFromNames(sys.argv[1:])
result = unittest.TextTestRunner(stream=out, verbosity=2).run(suite)
with open(os.path.join(ROOT, "output", "_tests.log"), "w", encoding="utf-8") as fh:
    fh.write(out.getvalue())
    fh.write("SUCCESS=%s RAN=%s FAILURES=%s ERRORS=%s SKIPPED=%s\n" % (
        result.wasSuccessful(), result.testsRun,
        len(result.failures), len(result.errors), len(result.skipped)))
sys.exit(0 if result.wasSuccessful() else 1)
