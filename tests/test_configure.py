import pathlib
import subprocess
import sys
import unittest

from ekernel import Kernel
from tests import capture_stdout, capture_stderr, colorless, Interceptor
import tests.data.kernel as data

import ekernel

def run (*argv):
    return ekernel.configure(list(argv))

class Tests (unittest.TestCase):

    def set_kernel (self, kernel):
        self.kernel = kernel
        self.kernel.oldconfig = self.kernel.config.with_suffix(".old")
        self.kernel.newoptions = self.kernel.src / ".newoptions"

    def setUp (self):
        # start interceptor
        self.interceptor = Interceptor()
        def run (tracer, *args, **kwargs):
            if args[0][0] == "make":
                if args[0][1] == "listnewconfig":
                    make = subprocess.CompletedProcess("", 0)
                    make.stdout = data.newoptions.encode()
                    return make
                elif args[0][1] == "menuconfig":
                    self.kernel.config.touch()
                elif args[0][1] == "oldconfig":
                    self.kernel.oldconfig.touch()
        self.interceptor.add(subprocess.run, call=run)
        self.interceptor.start()
        # setup test environment
        data.setup()
        self.set_kernel(Kernel.latest())

    def tearDown (self):
        # stop interceptor
        self.interceptor.stop()

    def check_list (self):
        # make listnewconfig
        tracer, (args, kwargs) = self.interceptor.trace[0]
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["make", "listnewconfig"],))
        self.assertEqual(kwargs, {"capture_output": True})
        self.assertTrue(self.kernel.newoptions.exists())

    def check_oldconfig (self):
        self.assertEqual(pathlib.Path.cwd(), self.kernel.src)
        # make listnewconfig
        self.check_list()
        self.assertTrue(self.kernel.config.exists())
        # make oldconfig
        tracer, (args, kwargs) = self.interceptor.trace[1]
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["make", "oldconfig"],))
        self.assertEqual(kwargs, {"check": True})
        self.assertTrue(self.kernel.config.exists())
        self.assertTrue(self.kernel.oldconfig.exists())

    def check_menuconfig (self):
        self.assertEqual(pathlib.Path.cwd(), self.kernel.src)
        # make menuconfig
        tracer, (args, kwargs) = self.interceptor.trace[0]
        self.assertEqual(tracer.name, "subprocess.run")
        self.assertEqual(args, (["make", "menuconfig"],))
        self.assertEqual(kwargs, {"check": True})
        self.assertTrue(self.kernel.config.exists())

    def test_configure_list_newopts_exists (self):
        self.kernel.config.touch()
        self.kernel.newoptions.touch()
        self.assertEqual(run("-l"), 0)
        self.assertFalse(self.interceptor.trace)

    @colorless
    @capture_stdout
    def test_configure_list_newopts_exists (self):
        self.kernel.newoptions.touch()
        self.assertEqual(run("-l"), 0)
        self.check_list()
        self.assertEqual(sys.stdout.getvalue(),
            f" * copying {Kernel.current().config}\n"
            " * running make listnewconfig\n"
            "   CONFIG_D = n\n"
            "   CONFIG_E = n\n"
            "   CONFIG_F = n\n"
        )

    @colorless
    @capture_stdout
    def test_configure_list_newopts_missing_config_missing (self):
        self.assertEqual(run("-l"), 0)
        self.check_list()
        self.assertEqual(sys.stdout.getvalue(),
            f" * copying {Kernel.current().config}\n"
            " * running make listnewconfig\n"
            "   CONFIG_D = n\n"
            "   CONFIG_E = n\n"
            "   CONFIG_F = n\n"
        )

    @colorless
    @capture_stderr
    def test_configure_list_newopts_missing_config_exists (self):
        self.kernel.config.touch()
        with self.assertRaises(SystemExit):
            run("-l")
        self.assertEqual(sys.stderr.getvalue(),
            f" * error: missing {self.kernel.newoptions}\n"
        )

    @colorless
    @capture_stderr
    def test_configure_list_newopts_missing_oldconfig_missing (self):
        Kernel.current().config.unlink()
        with self.assertRaises(SystemExit):
            run("-l")
        self.assertEqual(sys.stderr.getvalue(),
            f" * error: missing {self.kernel.newoptions}\n"
        )

    @colorless
    @capture_stdout
    def test_configure_oldconfig (self):
        self.assertEqual(run(), 0)
        self.check_oldconfig()
        self.assertEqual(sys.stdout.getvalue(),
            f" * copying {Kernel.current().config}\n"
            " * running make listnewconfig\n"
            " * running make oldconfig\n"
        )

    @colorless
    @capture_stdout
    def test_configure_oldconfig_older_version (self):
        self.set_kernel(data.kernels[-1])
        self.assertEqual(run("-s", str(self.kernel.src)), 0)
        self.check_menuconfig()
        self.assertEqual(sys.stdout.getvalue(), " * running make menuconfig\n")

    @colorless
    @capture_stdout
    def test_configure_new_exists (self):
        self.kernel.config.touch()
        self.assertEqual(run(), 0)
        self.check_menuconfig()
        self.assertEqual(sys.stdout.getvalue(), " * running make menuconfig\n")

    @colorless
    @capture_stdout
    def test_configure_old_missing (self):
        Kernel.current().config.unlink()
        run()
        self.check_menuconfig()
        self.assertEqual(sys.stdout.getvalue(), " * running make menuconfig\n")

    @colorless
    @capture_stdout
    def test_reconfigure_oldconfig (self):
        self.kernel.config.touch()
        run("-d")
        self.check_oldconfig()
        self.assertEqual(sys.stdout.getvalue(),
            f" * deleting {self.kernel.config}\n"
            f" * copying {Kernel.current().config}\n"
            " * running make listnewconfig\n"
            " * running make oldconfig\n"
        )

    @colorless
    @capture_stdout
    def test_reconfigure_menuconfig (self):
        self.kernel.config.touch()
        Kernel.current().config.unlink()
        run("-d")
        self.check_menuconfig()
        self.assertEqual(sys.stdout.getvalue(),
            f" * deleting {self.kernel.config}\n"
            " * running make menuconfig\n"
        )
