import os
import subprocess
import unittest

from test import Interceptor

class Foo:

    def __init__ (self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def bar (self, argv):
        subprocess.run(argv, stderr=subprocess.DEVNULL, check=True)

class Tests (unittest.TestCase):

    def setUp (self):
        self.interceptor = Interceptor()
        self.interceptor.add(subprocess.run)

    def tearDown (self):
        self.interceptor.stop()

    def test_add_duplicate (self):
        with self.assertRaisesRegex(RuntimeError, r".*already caught"):
            self.interceptor.add(subprocess.run)

    def test_add_not_callable (self):
        with self.assertRaisesRegex(RuntimeError, r".*not callable"):
            self.interceptor.add(os.abc)

    def test_remove_missing (self):
        with self.assertRaisesRegex(RuntimeError, r".*not being caught"):
            self.interceptor.remove(os.abc)

    def test_start (self):
        argv = ["cat", "something"]
        with self.assertRaises(subprocess.CalledProcessError):
            Foo().bar(argv)
        self.interceptor.start()
        Foo().bar(argv)

    def test_stop (self):
        argv = ["cat", "something"]
        self.interceptor.start()
        Foo().bar(argv)
        self.interceptor.stop()
        with self.assertRaises(subprocess.CalledProcessError):
            Foo().bar(argv)

    def test_trace (self):
        def test ():
            Foo().bar(argv)
            tracer, (args, kwargs) = self.interceptor.trace[-1]
            self.assertEqual(tracer.name, "subprocess.run")
            self.assertEqual(tracer.log, True)
            self.assertEqual(tracer.call, None)
            self.assertEqual(args, (argv,))
            self.assertEqual(
                kwargs,
                {"check": True, "stderr": subprocess.DEVNULL}
            )
        self.interceptor.start()
        argv = ["cat", "something"]
        test()
        argv = ["cat", "something", "else"]
        test()

    def test_trace_no_log (self):
        def test ():
            Foo().bar(argv)
            self.assertFalse(self.interceptor.trace)
        self.interceptor.targets[subprocess.run].log = False
        self.interceptor.start()
        argv = ["cat", "something"]
        test()
        argv = ["cat", "something", "else"]
        test()

    def test_call_library (self):
        def call (tracer, *args, **kwargs):
            self.assertTrue(tracer.interceptor is self.interceptor)
            return f"call({args}, {kwargs})"
        self.interceptor.remove(subprocess.run)
        self.interceptor.add(subprocess.run, call=call)
        self.interceptor.start()
        ret = subprocess.run("foo", "bar", foo="bar")
        self.assertEqual(ret, "call(('foo', 'bar'), {'foo': 'bar'})")
        self.assertEqual(len(self.interceptor.trace), 1)

    def test_call_constructor (self):
        def call (tracer, *args, **kwargs):
            self.assertTrue(tracer.interceptor is self.interceptor)
            tracer.target(*args, **kwargs)
        self.interceptor.add(Foo.__init__, log=False, call=call)
        self.interceptor.start()
        obj = Foo("foo", "bar", foo="bar")
        self.assertEqual(obj.args, ("foo", "bar"))
        self.assertEqual(obj.kwargs, {"foo": "bar"})
        self.assertFalse(self.interceptor.trace)

    def test_call_member (self):
        def call (tracer, *args, **kwargs):
            self.assertTrue(tracer.interceptor is self.interceptor)
            return args[1]
        self.interceptor.add(Foo.bar, log=False, call=call)
        self.interceptor.start()
        argv = ["cat", "something"]
        self.assertEqual(Foo().bar(argv), argv)
        self.assertFalse(self.interceptor.trace)
