import os
import subprocess
import sys
import unittest

from ekernel import Kernel
from tests import capture_stdout, capture_stderr, git, Interceptor
import tests.data.kernel as data

import ekernel

def run (*argv):
    return ekernel.update(list(argv))

class Tests (unittest.TestCase):

    def setUp (self):
        # setup test environment
        data.setup()
        self.latest = Kernel.latest()
        self.oldconfig = data.latest / ".config.old"
        # initialize git repository
        os.chdir(data.tmp)
        git(["init"])
        git(["config", "user.email", "some@e.mail"])
        git(["config", "user.name", "some body"])
        git(["add", "-f", Kernel.current().config])
        git(["commit", "-m", "initial"])
        # start interceptor
        @data.efi
        def run (tracer, *args, **kwargs):
            if args[0][0] == "make":
                if args[0][1] == "listnewconfig":
                    make = subprocess.CompletedProcess("", 0)
                    make.stdout = data.newoptions.encode()
                    return make
                elif args[0][1] == "oldconfig":
                    self.latest.config.write_text(data.newconfig)
                    self.oldconfig.write_text(data.oldconfig)
                elif args[0][1] == "-j":
                    self.latest.bzImage.touch()
                elif args[0][1] == "modules_install":
                    self.latest.modules.mkdir(parents=True)
            elif args[0][0] == "eselect":
                data.linux.unlink()
                data.linux.symlink_to(data.latest)
            elif args[0][0] == "git":
                return tracer.target(*args, **kwargs)
        self.interceptor = Interceptor()
        self.interceptor.add(subprocess.run, call=run)
        self.interceptor.start()

    def check_update (self):
        self.assertEqual(
            len([
                x for x in self.interceptor.trace
                if "mount" in x[1][0][0][0]
            ]),
            2
        )
        # configure
        self.assertTrue(self.oldconfig.exists())
        self.assertTrue(self.latest.config.exists())
        # install
        self.assertTrue(ekernel.efi.boot.exists())
        self.assertTrue(self.latest.bkp.exists())
        # clean
        for k in data.kernels[2:]:
            self.assertFalse(k.src.exists())
            self.assertFalse(k.modules.exists())
            self.assertFalse(k.bkp.exists())
        # check if config has been commited
        self.assertEqual(
            git([
                "cat-file",
                "-e",
                f"HEAD:{self.latest.config.relative_to(data.tmp)}"]
            ).returncode,
            0
        )

    def tearDown (self):
        # stop interceptor
        self.interceptor.stop()

    def test_update (self):
        self.assertEqual(run("-q"), 0)
        self.check_update()

    def test_update_jobs (self):
        self.assertEqual(run("-q", "-j", "8"), 0)
        self.check_update()

    def test_update_source (self):
        self.assertEqual(run("-q", "-s", str(data.latest)), 0)
        self.check_update()

    def test_update_keep (self):
        current = Kernel.current()
        self.assertEqual(run("-q", "-k", "1"), 0)
        self.check_update()
        self.assertFalse(current.src.exists())
        self.assertFalse(current.modules.exists())
        self.assertFalse(current.bkp.exists())

    @capture_stdout
    def test_update_message (self):
        self.assertEqual(run("-q", "-m", "details"), 0)
        self.check_update()
        self.assertIn(sys.stdout.getvalue(), "details\n")

    def test_update_jobs_source (self):
        self.assertEqual(run("-q", "-j", "8", "-s", str(data.latest)), 0)
        self.check_update()

    @capture_stderr
    def test_update_jobs_illegal (self):
        with self.assertRaises(SystemExit):
            run("-j", "foo")

    @capture_stderr
    def test_update_source_illegal (self):
        with self.assertRaises(SystemExit):
            run("-s", "/foobar")
