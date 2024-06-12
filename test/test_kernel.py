import shutil
import unittest

from packaging.version import Version

from test import Interceptor
import test.data.kernel as data

import ekernel

class Tests (unittest.TestCase):

    def setUp (self):
        data.setup()

    def check_vars (self, k, s):
        v = ekernel.version(s.name)
        self.assertEqual(k.version, v)
        self.assertEqual(k.src, s)
        self.assertEqual(k.config, s / ".config")
        self.assertEqual(k.bzImage, s / "arch/x86_64/boot/bzImage")
        self.assertEqual(k.modules, data.modules / f"{v.base_version}-gentoo")
        self.assertEqual(
            k.bkp,
            data.boot.parent / f"gentoo-{v.base_version}.efi"
        )

    def test_kernel_paths (self):
        self.assertEqual(ekernel.Kernel.src, data.src)
        self.assertEqual(ekernel.Kernel.linux, data.linux)
        self.assertEqual(ekernel.Kernel.modules, data.modules)

    def test_kernel_version (self):
        self.assertEqual(ekernel.version("0.0.1-gentoo"), Version("0.0.1"))

    def test_kernel_constructor (self):
        self.check_vars(
            ekernel.Kernel(data.current),
            ekernel.Kernel.current().src
        )

    def test_kernel_list (self):
        self.assertEqual(ekernel.Kernel.list(), data.kernels)

    def test_kernel_list_ascending (self):
        self.assertEqual(
            ekernel.Kernel.list(descending=False),
            list(reversed(data.kernels))
        )

    def test_kernel_current (self):
        self.check_vars(ekernel.Kernel.current(), data.current)

    def test_kernel_latest (self):
        self.check_vars(ekernel.Kernel.latest(), data.latest)

    def test_kernel_eq (self):
        self.assertEqual(
            ekernel.Kernel.current(),
            ekernel.Kernel(data.current)
        )

    def test_kernel_neq (self):
        self.assertNotEqual(ekernel.Kernel.current(), ekernel.Kernel.latest())

    def test_kernel_bootable (self):
        self.assertFalse(ekernel.Kernel.latest().bootable())
        self.assertTrue(ekernel.Kernel.current().bootable())

    def test_kernel_current_missing (self):
        kernel = ekernel.Kernel.current()
        shutil.rmtree(kernel.src)
        with self.assertRaises(ValueError) as e:
            ekernel.Kernel.current()
        self.assertEqual(
            str(e.exception),
            f"error: missing source {kernel.src}"
        )
