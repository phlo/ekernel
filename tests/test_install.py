import subprocess
import sys
import unittest

from ekernel import Kernel
from tests import capture_stderr, Interceptor
import tests.data.kernel as data

import ekernel

def run (*argv):
    return ekernel.install(list(argv))

class Tests (unittest.TestCase):

    def setUp (self):
        # setup test environment
        data.setup()
        self.kernel = Kernel.latest()
        self.kernel.bzImage.touch()
        # start interceptor
        @data.efi
        def run (tracer, *args, **kwargs):
            if args[0][0] == "eselect":
                data.linux.unlink()
                data.linux.symlink_to(self.kernel.src.name)
        self.interceptor = Interceptor()
        self.interceptor.add(subprocess.run, call=run)
        self.interceptor.start()

    def tearDown (self):
        # stop interceptor
        self.interceptor.stop()

    def check_install (self):
        trace_it = iter(self.interceptor.trace)
        # efibootmgr
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["efibootmgr"],))
        self.assertEqual(kwargs, {"capture_output": True, "check": True})
        # mount /boot
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["mount", "/boot"],))
        self.assertEqual(kwargs, {"capture_output": True, "check": True})
        # eselect kernel set <name>
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(
            args,
            (["eselect", "kernel", "set", self.kernel.src.name],)
        )
        self.assertEqual(kwargs, {"check": True})
        self.assertEqual(str(data.linux.readlink()), self.kernel.src.name)
        # emerge @module-rebuild
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["emerge", "@module-rebuild"],))
        self.assertEqual(kwargs, {"check": True})
        # umount /boot
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["umount", "/tmp"],))
        self.assertEqual(kwargs, {"check": True})
        # check generated files
        self.assertTrue(self.kernel.boot.exists())
        self.assertTrue(self.kernel.bkp.exists())

    def test_install (self):
        self.assertEqual(run("-q"), 0)
        self.check_install()

    def test_install_source (self):
        self.kernel = Kernel.current()
        self.assertEqual(run("-q", "-s", str(data.current)), 0)
        self.check_install()

    @capture_stderr
    def test_install_missing_bzImage (self):
        self.kernel.bzImage.unlink()
        with self.assertRaises(SystemExit):
            self.assertEqual(run("-s", str(data.latest)), 1)
        self.assertRegex(sys.stderr.getvalue(), r"missing.*bzImage")
