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
        os.chdir(data.root)
        for k in data.kernels[:-2]:
            if not k.config.exists():
                k.config.touch()
            if not k.modules.exists():
                k.modules.mkdir(parents=True)
            if not k.efi.exists():
                k.efi.touch()
        # start interceptor
        self.interceptor = Interceptor()
        self.interceptor.add(subprocess.run, call=True)
        self.interceptor.start()

    def tearDown (self):
        # stop interceptor
        self.interceptor.stop()

    def check_clean (self, keep=1):
        split = data.kernels.index(Kernel.current()) + keep + 1
        trace_it = iter(self.interceptor.trace)
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
        for k in data.kernels[:split]:
            self.assertTrue(k.src.exists())
            self.assertTrue(k.modules.exists())
            self.assertTrue(k.efi.exists())
        for k in data.kernels[split:]:
            self.assertFalse(k.src.exists())
            self.assertFalse(k.modules.exists())
            self.assertFalse(k.efi.exists())
        # umount /boot
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["umount", "/boot"],))
        self.assertEqual(kwargs, {"check": True})

    def test_clean (self):
        self.assertEqual(run("-q"), 0)
        self.check_clean()

    def test_clean_missing_efi (self):
        data.kernels[-1].efi.unlink()
        self.assertEqual(run("-q"), 0)
        self.check_clean()

    def test_clean_missing_modules (self):
        shutil.rmtree(data.kernels[-1].modules)
        self.assertEqual(run("-q"), 0)
        self.check_clean()

    def test_clean_keep_2 (self):
        self.assertEqual(run("-q", "-k", "2"), 0)
        self.check_clean(2)

    def test_clean_keep_none (self):
        self.assertEqual(run("-q", "-k", "0"), 0)
        self.check_clean(0)

    def test_clean_keep_gt_available (self):
        self.assertEqual(run("-q", "-k", "10"), 0)
        self.check_clean(10)

    def test_clean_esp (self):
        esp = data.root / "boot/EFI/linux"
        esp.mkdir(parents=True)
        for k in data.kernels:
            efi = esp / k.efi.name
            if k.efi.exists():
               efi.touch()
            k.efi.unlink()
            k.efi = efi
        data.esp.rmdir()
        self.assertEqual(run("-q", "-e", str(esp)), 0)
        self.check_clean()

    @colorless
    @capture_stdout
    def test_clean_dry_run (self):
        self.assertEqual(run("-n"), 0)
        for src in data.sources:
            self.assertTrue(src.exists())
        expected = io.StringIO()
        expected.write(f" * the following kernels will be removed:\n")
        for k in data.kernels[2:]:
            expected.write(f"   ✗ {k.src.name}\n")
        self.assertEqual(sys.stdout.getvalue(), expected.getvalue())
