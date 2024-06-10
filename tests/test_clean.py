import io
import os
import shutil
import subprocess
import sys
import unittest

from ekernel import Kernel
from tests import capture_stdout, colorless, Interceptor
import tests.data.kernel as data

import ekernel

def run (*argv):
    return ekernel.clean(list(argv))

class Tests (unittest.TestCase):

    def setUp (self):
        # setup test environment
        data.setup()
        # update src symlink to new kernel
        data.linux.unlink()
        data.linux.symlink_to(data.latest)
        # initialize git repository
        os.chdir(data.tmp)
        for k in data.kernels[:-2]:
            if not k.config.exists():
                k.config.touch()
            if not k.modules.exists():
                k.modules.mkdir(parents=True)
            if not k.bkp.exists():
                k.bkp.touch()
        # start interceptor
        @data.efi
        def run (tracer, *args, **kwargs): pass
        self.interceptor = Interceptor()
        self.interceptor.add(subprocess.run, call=run)
        self.interceptor.start()

    def tearDown (self):
        # stop interceptor
        self.interceptor.stop()

    def check_clean (self, keep=2):
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
        # emerge -cq gentoo-sources
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["emerge", "-cq", "gentoo-sources"],))
        self.assertEqual(kwargs, {})
        if keep < 3:
            # efibootmgr -b 0003 -B
            tracer, (args, kwargs) = next(trace_it)
            self.assertEqual(tracer.name, "subprocess.run")
            self.assertEqual(args, (["efibootmgr", "-q", "-b", "0003", "-B"],))
            self.assertEqual(kwargs, {"check": True})
        # umount /boot
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["umount", "/tmp"],))
        self.assertEqual(kwargs, {"check": True})
        # check files
        for k in data.kernels[:keep]:
            self.assertTrue(k.src.exists())
            self.assertTrue(k.modules.exists())
            self.assertTrue(k.bkp.exists())
        for k in data.kernels[keep:]:
            self.assertFalse(k.src.exists())
            self.assertFalse(k.modules.exists())
            self.assertFalse(k.bkp.exists())

    def test_clean (self):
        self.assertEqual(run("-q"), 0)
        self.check_clean()

    def test_clean_missing_efi (self):
        data.kernels[-1].bkp.unlink()
        self.assertEqual(run("-q"), 0)
        self.check_clean()

    def test_clean_missing_modules (self):
        shutil.rmtree(data.kernels[-1].modules)
        self.assertEqual(run("-q"), 0)
        self.check_clean()

    def test_clean_keep_3 (self):
        self.assertEqual(run("-q", "-k", "3"), 0)
        self.check_clean(3)

    def test_clean_keep_none (self):
        with self.assertRaises(SystemExit):
            run("-q", "-k", "0")

    def test_clean_keep_gt_available (self):
        self.assertEqual(run("-q", "-k", "10"), 0)
        self.check_clean(10)

    @capture_stdout
    def test_clean_umount_on_error (self):
        with self.assertRaises(SystemExit):
            run("-h")
        tracer, (args, kwargs) = self.interceptor.trace[-1]
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["umount", "/tmp"],))
        self.assertEqual(kwargs, {"check": True})

    @colorless
    @capture_stdout
    def test_clean_dry_run (self):
        self.assertEqual(run("-n"), 0)
        for src in data.sources:
            self.assertTrue(src.exists())
        kernels = data.kernels[2:]
        rm = {
            "sources": [k.src for k in kernels],
            "modules": [k.modules for k in kernels],
            "images": [k.bkp for k in kernels]
        }
        expected = io.StringIO()
        expected.write(" * running emerge -cq gentoo-sources\n")
        for k, v in rm.items():
            expected.write(f" * deleting {k}:\n")
            for p in v:
                expected.write(f"   ✗ {p}\n")
        expected.write(" * deleting boot entry Gentoo (fallback)\n")
        self.assertEqual(sys.stdout.getvalue(), expected.getvalue())
