import pathlib
import subprocess
import unittest

from ekernel import Kernel
from tests import capture_stderr, Interceptor
import tests.data.kernel as data

import ekernel

def run (*argv):
    return ekernel.build(list(argv))

class Tests (unittest.TestCase):

    def setUp (self):
        # start interceptor
        self.interceptor = Interceptor()
        def run (tracer, *args, **kwargs):
            if args[0][0] == "make" and args[0][1] == "-j":
                self.kernel.bzImage.touch()
        self.interceptor.add(subprocess.run, call=run)
        self.interceptor.start()
        # setup test environment
        data.setup()
        self.kernel = Kernel.latest()
        self.kernel.config.touch()
        self.jobs = "4"

    def tearDown (self):
        # stop interceptor
        self.interceptor.stop()

    def check_build (self):
        self.assertEqual(pathlib.Path.cwd(), self.kernel.src)
        trace_it = iter(self.interceptor.trace)
        # make -j <jobs>
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["make", "-j", self.jobs],))
        self.assertEqual(kwargs, {"check": True})
        self.assertTrue(self.kernel.bzImage.exists())
        # make modules_install
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["make", "modules_install"],))
        self.assertEqual(kwargs, {"check": True})

    def test_build (self):
        self.assertEqual(run("-q"), 0)
        self.check_build()

    def test_build_jobs (self):
        self.jobs = "128"
        self.assertEqual(run("-q", "-j", self.jobs), 0)
        self.check_build()

    @capture_stderr
    def test_build_jobs_illegal (self):
        with self.assertRaises(SystemExit):
            run("-j", "foo")

    def test_build_source (self):
        self.kernel = Kernel.current()
        self.kernel.config.touch()
        self.assertEqual(run("-q", "-s", str(data.current)), 0)
        self.check_build()

    @capture_stderr
    def test_build_source_missing (self):
        with self.assertRaises(SystemExit):
            run("-s", str(data.src / "linux-0.0.0-gentoo"))

    def test_build_source_missing_config (self):
        Kernel.latest().config.unlink()
        with self.assertRaises(SystemExit):
            self.assertEqual(run("-q", "-s", str(data.latest)), 1)

    @capture_stderr
    def test_build_source_illegal (self):
        with self.assertRaises(SystemExit):
            run("-s", str(data.tmp))

    def test_build_jobs_source (self):
        self.jobs = "128"
        self.assertEqual(run("-q", "-j", self.jobs, "-s", str(data.latest)), 0)
        self.check_build()
