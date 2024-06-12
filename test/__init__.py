import functools
import io
import subprocess
import sys

import portage.output
from pkgutil import resolve_name as resolve

import ekernel

# disable output
ekernel.out.quiet = True

def git (argv: list[str]):
    return subprocess.run(["git"] + argv, capture_output=True, check=True)

def capture_stdout (f):
    """A decorator for capturing stdout in a io.StringIO object."""
    @functools.wraps(f)
    def capture (*args, **kwargs):
        quiet = ekernel.out.quiet
        ekernel.out.quiet = False
        stdout = sys.stdout
        sys.stdout = io.StringIO()
        r = f(*args, **kwargs)
        sys.stdout = stdout
        ekernel.out.quiet = quiet
        return r
    return capture

def capture_stderr (f):
    """A decorator for capturing stderr in a io.StringIO object."""
    @functools.wraps(f)
    def capture (*args, **kwargs):
        quiet = ekernel.out.quiet
        ekernel.out.quiet = False
        stderr = sys.stderr
        sys.stderr = io.StringIO()
        r = f(*args, **kwargs)
        sys.stderr = stderr
        ekernel.out.quiet = quiet
        return r
    return capture

def colorless (f):
    """A decorator for disabling portage's colorful output."""
    @functools.wraps(f)
    def nocolor (*args, **kwargs):
        havecolor = portage.output.havecolor
        portage.output.havecolor = 0
        r = f(*args, **kwargs)
        portage.output.havecolor = havecolor
        return r
    return nocolor

class Interceptor:
    """Dynamically intercept, trace and/or replace arbitrary function calls."""

    class Tracer:

        def __init__ (self, interceptor, target, log, call):
            self.name = f"{target.__module__}.{target.__qualname__}"
            self.parent = resolve(self.name.rsplit(".", 1)[0])
            self.interceptor = interceptor
            self.target = target
            self.log = log
            self.call = call

        def start (self):
            def call (*args, **kwargs):
                if self.log:
                    self.interceptor.trace.append((self, (args, kwargs)))
                if callable(self.call):
                    return self.call(self, *args, **kwargs)
            setattr(self.parent, self.target.__name__, call)

        def stop (self):
            setattr(self.parent, self.target.__name__, self.target)

    def __init__ (self):
        self.targets = {}
        self.trace = []

    def __str__ (self):
        s = io.StringIO()
        for tracer, (args, kwargs) in self.trace:
            s.write(f"{tracer.name}\n")
            for a in args:
                s.write(f"  {a}\n")
            for k, v in kwargs.items():
                s.write(f"  {k} = {v}\n")
        return s.getvalue()

    def add (self, target, log=True, call=None):
        """
        Intercept calls to the given function.

        Args:
            target: the intercepted function object
            log (bool): trace calls if True
            call: function to be called instead
        """
        if target in self.targets:
            raise RuntimeError(f"{self.targets[target].name} already caught")
        if not callable(target):
            raise RuntimeError(f"{target.__name__} is not callable")
        self.targets[target] = self.Tracer(self, target, log, call)

    def remove (self, target):
        """Stop intercepting calls to the given function."""
        if target not in self.targets:
            raise RuntimeError(f"{target.__name__} not being caught")
        del self.targets[target]

    def start (self):
        """Start intercepting calls to the registered functions."""
        for tracer in self.targets.values(): tracer.start()

    def stop (self):
        """Stop intercepting calls to the registered functions."""
        for tracer in self.targets.values(): tracer.stop()
