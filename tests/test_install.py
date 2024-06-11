import platform
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
        self.current = Kernel.current()
        # start interceptor
        @data.efi
        def run (tracer, *args, **kwargs):
            if args[0][0] == "findmnt":
                return subprocess.CompletedProcess("", 0, b"/dev/sda1")
            elif args[0][0] == "eselect":
                data.linux.unlink()
                data.linux.symlink_to(self.kernel.src.name)
        def release (tracer, *args, **kwargs):
            return f"{self.current.version.base_version}-gentoo"
        self.interceptor = Interceptor()
        self.interceptor.add(subprocess.run, call=run)
        self.interceptor.add(platform.release, call=release)
        self.interceptor.start()

    def tearDown (self):
        # stop interceptor
        self.interceptor.stop()

    def check_install (self, backup=False):
        trace_it = iter(self.interceptor.trace)
        # efibootmgr
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["efibootmgr"],))
        self.assertEqual(kwargs, {"capture_output": True, "check": True})
        # mount <boot>
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
        # make modules_install
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["make", "modules_install"],))
        self.assertEqual(kwargs, {"check": True})
        # emerge @module-rebuild
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["emerge", "-q", "@module-rebuild"],))
        self.assertEqual(kwargs, {"check": True})
        if backup:
            if data.boot.read_bytes() == b"missing image":
                # platform.release
                tracer, (args, kwargs) = next(trace_it)
                self.assertEqual(tracer.name, "platform.release")
            # findmnt -rno SOURCE <boot>
            tracer, (args, kwargs) = next(trace_it)
            self.assertEqual(tracer.name, "subprocess.run")
            self.assertEqual(args, (["findmnt", "-rno", "SOURCE", "/tmp"],))
            self.assertEqual(kwargs, {"capture_output": True, "check": True})
            # efibootmgr -b 0003 -B
            tracer, (args, kwargs) = next(trace_it)
            self.assertEqual(tracer.name, "subprocess.run")
            self.assertEqual(args, (["efibootmgr", "-q", "-b", "0003", "-B"],))
            self.assertEqual(kwargs, {"check": True})
            # efibootmgr -c -d <disk> -p <part> -L <label> -l <loader>
            tracer, (args, kwargs) = next(trace_it)
            self.assertEqual(tracer.name, "subprocess.run")
            self.assertEqual(args, ([
                "efibootmgr",
                "-q",
                "-c",
                "-d", "/dev/sda",
                "-p", "1",
                "-L", "Gentoo (fallback)",
                "-l", str(self.current.bkp)
            ],))
            self.assertEqual(kwargs, {"check": True})
        # umount <boot>
        tracer, (args, kwargs) = next(trace_it)
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["umount", "/tmp"],))
        self.assertEqual(kwargs, {"check": True})
        # check generated files
        self.assertTrue(ekernel.efi.img.exists())
        self.assertTrue(self.kernel.bkp.exists())

    def test_install (self):
        self.assertEqual(run("-q"), 0)
        self.check_install()

    def test_install_source (self):
        self.kernel = Kernel.current()
        self.assertEqual(run("-q", "-s", str(data.current)), 0)
        self.check_install()

    def test_install_backup (self):
        self.assertEqual(run("-q", "-b"), 0)
        self.check_install(backup=True)

    def test_install_backup_missing_image (self):
        self.current.bkp.unlink()
        self.kernel.bzImage.write_bytes(b"missing image")
        self.assertEqual(run("-q", "-b"), 0)
        self.check_install(backup=True)
        self.assertTrue(self.current.bkp.exists())

    @capture_stderr
    def test_install_missing_bzImage (self):
        self.kernel.bzImage.unlink()
        with self.assertRaises(SystemExit):
            run("-s", str(data.latest))
        self.assertRegex(sys.stderr.getvalue(), r"missing.*bzImage")
        tracer, (args, kwargs) = self.interceptor.trace[-1]
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["umount", "/tmp"],))
        self.assertEqual(kwargs, {"check": True})
