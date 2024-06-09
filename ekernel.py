import argparse
import difflib
import functools
import io
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys

from packaging.version import Version
from portage import output, colorize

__version__ = "0.1"

# number of parallel build jobs
jobs = "4"

# gentoo's fancy terminal output functions
out = output.EOutput()
out.print = lambda s: print(s) if not out.quiet else None
out.hilite = lambda s: colorize("HILITE", str(s))

# disable colorization for pipes and redirects
if not sys.stdout.isatty():
    output.havecolor = 0

def version (string: str):
    """Extract the version from a given string."""
    return Version("".join(filter(
        None,
        re.search(r"(\d+.\d+.\d+)-gentoo(-\w+\d+)?", string).groups()
    )))

class Kernel:

    # kernel source directory
    src = pathlib.Path("/usr/src")

    # kernel source symlink
    linux = src / "linux"

    # module directory
    modules = pathlib.Path("/lib/modules")

    def __init__ (self, src):
        """Construct a Kernel based on a given source path."""
        self.src = pathlib.Path(src)
        if not self.src.exists():
            raise ValueError(f"missing source: {src}")
        try:
            self.version = version(self.src.name)
        except Exception as e:
            raise ValueError(f"illegal source: {src}") from e
        self.config = self.src / ".config"
        self.bzImage = self.src / "arch/x86_64/boot/bzImage"
        self.bkp = efi.boot.parent / f"gentoo-{self.version.base_version}.efi"
        self.modules = self.modules / f"{self.version.base_version}-gentoo"

    def __eq__ (self, other):
        if not isinstance(other, Kernel):
            return False
        return self.src == other.src

    def __str__ (self):
        return (
            f"{self.src.name}\n"
            f"* version = {self.version}\n"
            f"* src     = {self.src}\n"
            f"* config  = {self.config}\n"
            f"* bzImage = {self.bzImage}\n"
            f"* modules = {self.modules}\n"
            f"* bkp     = {self.bkp}\n"
        )

    @classmethod
    def list (cls, descending=True):
        """Get an descending list of available kernels."""
        return list(sorted(
            (Kernel(src) for src in cls.src.glob("linux-*")),
            key=lambda k: k.version,
            reverse=descending
        ))

    @classmethod
    def current (cls):
        """
        Get the currently running kernel.

        Returns:
            Kernel: the current kernel, pointed to by ``/usr/src/linux``
        """
        return cls(Kernel.linux.resolve())

    @classmethod
    def latest (cls):
        """
        Get the latest available kernel.

        Returns:
            Kernel: the newest kernel under ``/usr/src``
        """
        return cls.list()[0]

def cli (f):
    """A top level exception handling decorator for script main functions."""
    @functools.wraps(f)
    def handler (argv=sys.argv[1:]):
        try:
            r = f(argv)
            return 0 if r is None else r
        except Exception as e:
            out.eerror(str(e))
            sys.exit(1)
    return handler

def efi (f):
    """Decorator locating and mounting the ESP through efivars."""
    efi.skip = False
    # system partition
    efi.esp = pathlib.Path("/boot")
    # bootloader (stub kernel)
    efi.boot = efi.esp / "EFI/Gentoo/bootx64.efi"
    # backup entry data
    efi.bkp = {}
    # analyze boot entries and ensure access to the currently running image
    @functools.wraps(f)
    def locator (*args, **kwargs):
        # skip detection
        if efi.skip:
            return f(*args, **kwargs)
        efi.skip = True
        # get boot entries
        mgr = subprocess.run(
            ["efibootmgr"],
            capture_output=True,
            check=True
        )
        entries = mgr.stdout.decode().splitlines()
        bootnum = "NaN"
        for l in entries:
            if l.startswith("BootCurrent"):
                bootnum = l.split()[1]
                break
        # find currently running boot entry / loader
        def parse (entry):
            # label
            i = l.find(" ") + 1
            j = l.find("\t", i)
            label = l[i:j]
            # loader
            i = l.find("File", j)
            if i < 0:
                raise RuntimeError(f"error locating bootloader:\n{l}")
            i += 6
            j = l.find(")", i)
            loader = pathlib.Path(l[i:j].replace("\\", "/"))
            return label, loader
        for l in entries:
            if l.startswith(f"Boot{bootnum}"):
                label, loader = parse(l)
                efi.label = label
                efi.bkp["label"] = f"{label} (fallback)"
                break
        # find bootnum of backup entry
        for l in entries:
            if efi.bkp["label"] in l:
                efi.bkp["bootnum"] = l[4:8]
                break
        # mount esp
        mounted = False
        if not efi.boot.exists():
            # find mountpoint
            for l in pathlib.Path("/etc/fstab").read_text().splitlines():
                if not l.startswith("#"):
                    for p in ["/boot", "/efi"]:
                        if p in l:
                            efi.esp = pathlib.Path(p)
                            efi.boot = efi.esp / loader
                            break
                    else: continue
                    break
            else:
                raise RuntimeError("error finding ESP mountpoint")
            try:
                subprocess.run(
                    ["mount", str(efi.esp)],
                    capture_output=True,
                    check=True
                )
                mounted = True
            except subprocess.CalledProcessError as e:
                msg = e.stderr.decode().strip()
                if f"already mounted on {efi.esp}" not in msg:
                    raise RuntimeError(e.stderr.decode().splitlines()[0])
        assert efi.boot.exists()
        try:
            return f(*args, **kwargs)
        finally:
            efi.skip = False
            # umount esp
            if mounted:
                subprocess.run(["umount", str(efi.esp)], check=True)
    return locator

@cli
def configure (argv):
    """
    Configure a kernel.
    ===================

    Runs ``make menuconfig`` in the latest kernel's source directory if it is
    already configured, the current config missing or no other kernel is
    installed. Otherwise, configure the latest kernel with ``make oldconfig``,
    using the current kernel config.

    Command Line Arguments
    ----------------------

    ``-s <src>``
      kernel source directory (default: latest)

    ``-q``
      be quiet

    Files
    -----

    The following files are created in the new kernel's source directory,
    storing details about changes in the configuration:

    ``.newoptions``
      Newly added configuration options w.r.t. to the previous config (the
      output of ``make listnewconfig``).

    Process Outline
    ---------------

    This command is a mere wrapper to::

      if [[ ! -f ${old}/.config || $(ls -1dq /usr/src/linux-* | wc -l) == "1"]]
      then
        cd ${new}
        make menuconfig
      else
        cp -n ${old}/.config ${new}
        cd ${new}
        make listnewconfig > .newoptions
        make oldconfig || exit
      fi
    """
    parser = argparse.ArgumentParser(
        prog="ekernel-configure",
        description="Configure a kernel.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-l",
        dest="list",
        action="store_true",
        help="print newly added config options and exit"
    )
    parser.add_argument(
        "-d",
        dest="delete",
        action="store_true",
        help="delete config (perform a fresh install / reconfigure)"
    )
    parser.add_argument(
        "-s",
        metavar="<src>",
        dest="src",
        type=pathlib.Path,
        default=Kernel.latest().src,
        help="kernel source directory (default: latest)"
    )
    parser.add_argument(
        "-q",
        dest="quiet",
        action="store_true",
        help="be quiet"
    )
    args = parser.parse_args(argv)
    kernel = Kernel(args.src)
    out.quiet = args.quiet
    newoptions = kernel.src / ".newoptions"

    # check if current kernel config exists
    try:
        oldconfig = Kernel.current().config
    except FileNotFoundError:
        oldconfig = efi.esp / "FILENOTFOUND"

    # change to source directory
    os.chdir(kernel.src)

    # delete config - reconfigure
    if args.delete and kernel.config.exists():
        out.einfo(f"deleting {kernel.config}")
        kernel.config.unlink()

    # make oldconfig
    if not kernel.config.exists() and oldconfig.exists():
        # copy oldconfig
        out.einfo(f"copying {out.hilite(oldconfig)}")
        shutil.copy(oldconfig, kernel.config)
        # store newly added options
        out.einfo(f"running {out.hilite('make listnewconfig')}")
        make = subprocess.run(["make", "listnewconfig"], capture_output=True)
        newoptions.write_text(make.stdout.decode())
        # configure
        if not args.list:
            out.einfo(f"running {out.hilite('make oldconfig')}")
            subprocess.run(["make", "oldconfig"], check=True)
    # make menuconfig
    elif not args.list:
        out.einfo(f"running {out.hilite('make menuconfig')}")
        subprocess.run(["make", "menuconfig"], check=True)

    # check if we should print new options
    if args.list:
        if not newoptions.exists():
            raise FileNotFoundError(f"missing {newoptions}")
        for l in newoptions.read_text().splitlines():
            opt, val = l.split("=", maxsplit=1)
            out.print(f"   {opt} = {val}")

@cli
def build (argv):
    """
    Build a kernel.
    ===============

    Build the latest kernel found in ``/usr/src`` or any other by supplying
    a source directory and install it's modules.

    Command Line Arguments
    ----------------------

    ``-j <jobs>``
      number of parallel make jobs (default: 4)

    ``-s <src>``
      kernel source directory (default: latest)

    ``-q``
      be quiet

    Process Outline
    ---------------

    Changes into the kernel's source directory and builds the image.

    This command is a mere wrapper to::

      cd ${new}
      make -k ${jobs} && make modules_install
    """
    parser = argparse.ArgumentParser(
        prog="ekernel-build",
        description="Build a kernel.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-j",
        metavar="<jobs>",
        dest="jobs",
        type=int,
        default=int(jobs),
        help=f"number of parallel make jobs (default: {jobs})"
    )
    parser.add_argument(
        "-s",
        metavar="<src>",
        dest="src",
        type=pathlib.Path,
        default=Kernel.latest().src,
        help="kernel source directory (default: latest)"
    )
    parser.add_argument(
        "-q",
        dest="quiet",
        action="store_true",
        help="be quiet"
    )
    args = parser.parse_args(argv)
    kernel = Kernel(args.src)
    out.quiet = args.quiet

    # check if config exists
    if not kernel.config.exists():
        raise FileNotFoundError(f"missing config: {kernel.config}")

    # change directory
    os.chdir(kernel.src)

    # build and install modules
    out.einfo(f"building {out.hilite(kernel.src.name)}")
    subprocess.run(["make", "-j", str(args.jobs)], check=True)
    out.einfo("installing modules")
    subprocess.run(["make", "modules_install"], check=True)

@cli
@efi
def install (argv):
    """
    Install a kernel.
    =================

    Install the latest kernel found in ``/usr/src`` or any other by supplying
    it's source directory.

    Command Line Arguments
    ----------------------

    ``-b``
      create fallback boot entry (default: false)

    ``-s <src>``
      kernel source directory (default: latest)

    ``-q``
      be quiet

    Process Outline
    ---------------

    Update ``/usr/src`` to the given kernel, install it's ``bzImage`` into the
    EFI system partition as ``bootx64.efi`` and add a backup copy
    ``gentoo-${version}.efi`` in case something goes horribly wrong.

    This command is a mere wrapper to::

      eselect kernel set $(basename ${src})
      mount /boot
      esp=/boot/EFI/Gentoo
      cp ${src}/arch/x86_64/boot/bzImage ${esp}/bootx64.efi
      cp ${src}/arch/x86_64/boot/bzImage ${esp}/gentoo-${version}.efi
    """
    parser = argparse.ArgumentParser(
        prog="ekernel-install",
        description="Install a kernel.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-b",
        dest="bkp",
        action="store_true",
        help="create fallback boot entry"
    )
    parser.add_argument(
        "-s",
        metavar="<src>",
        dest="src",
        type=pathlib.Path,
        default=Kernel.latest().src,
        help="kernel source directory (default: latest)"
    )
    parser.add_argument(
        "-q",
        dest="quiet",
        action="store_true",
        help="be quiet"
    )
    args = parser.parse_args(argv)
    kernel = Kernel(args.src)
    out.quiet = args.quiet

    # check if bzImage exists
    if not kernel.bzImage.exists():
        raise FileNotFoundError(f"missing bzImage {kernel.bzImage}")

    # create backup boot entry
    if args.bkp:
        # path to backup image
        bkp = None
        # find the currently running kernel's backup image
        boot_bytes = efi.boot.read_bytes()
        for f in efi.boot.parent.glob("gentoo*.efi"):
            if f.read_bytes() == boot_bytes:
                bkp = f
                break
        # not found
        else:
            name = f"gentoo-{version(platform.release()).base_version}.efi"
            bkp = efi.boot.parent / name
            shutil.copy(efi.boot, bkp)
        # get ESP disk and partition number
        dev = subprocess.run(
            ["findmnt", "-rno", "SOURCE", str(efi.esp)],
            capture_output=True,
            check=True
        )
        disk, part = filter(
            None,
            re.search(r"([/a-z]+)(\d+)", dev.stdout.decode()).groups()
        )
        # remove previous entry
        if "bootnum" in efi.bkp:
            subprocess.run([
                "efibootmgr",
                "-q",
                "-b", efi.bkp["bootnum"],
                "-B"
            ], check=True)
        # create entry
        subprocess.run([
            "efibootmgr",
            "-q",
            "-c",
            "-d", disk,
            "-p", part,
            "-L", efi.bkp["label"],
            "-l", str(bkp)
        ], check=True)

    # update symlink to the new source directory
    out.einfo(
        "updating symlink "
        f"{out.hilite(kernel.linux)} → {out.hilite(kernel.src)}"
    )
    subprocess.run(
        ["eselect", "kernel", "set", kernel.src.name],
        check=True
    )

    # copy boot image
    out.einfo(f"creating boot image {out.hilite(efi.boot)}")
    shutil.copy(kernel.bzImage, efi.boot)

    # create backup
    out.einfo(f"creating backup image {out.hilite(kernel.bkp)}")
    shutil.copy(kernel.bzImage, kernel.bkp)

    # rebuild external modules
    out.einfo(f"rebuilding external kernel modules")
    subprocess.run(["emerge", "@module-rebuild"], check=True)

@cli
@efi
def clean (argv):
    """
    Remove unused kernel leftovers.
    ===============================

    Remove unused kernel source directories, modules and boot images.

    The default is to keep the ``k`` previous kernel versions in case something
    goes horribly wrong.

    Command Line Arguments
    ----------------------

    ``-k <num>``
      keep the previous ``<num>`` kernels (default: 1)

    ``-n``
      perform a dry run (show what would be removed)

    ``-q``
      be quiet

    """
    parser = argparse.ArgumentParser(
        prog="ekernel-clean",
        description="Remove unused kernel leftovers.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-k",
        metavar="<keep>",
        dest="keep",
        type=int,
        default=1,
        help="keep the previous <num> bootable kernels (default: 1)"
    )
    parser.add_argument(
        "-n",
        dest="dry",
        action="store_true",
        help="perform a dry run (show what would be removed)"
    )
    parser.add_argument(
        "-q",
        dest="quiet",
        action="store_true",
        help="be quiet"
    )
    args = parser.parse_args(argv)
    out.quiet = args.quiet
    if args.keep < 0:
        raise ValueError("invalid keep value: must be greater equal zero")

    # kernels to remove
    kernels = Kernel.list()
    def obsolete (k):
        if args.keep and k.bkp.exists() and k.modules.exists():
            args.keep -= 1
            return False
        return True
    leftovers = filter(obsolete, kernels[kernels.index(Kernel.current()) + 1:])

    # dry run
    if args.dry:
        if leftovers:
            out.einfo("the following kernels will be removed:")
            for k in leftovers:
                out.print(f"   {colorize('BAD', '✗')} {k.src.name}")
        else:
            out.einfo("nothing to see here")
        return

    # run depclean
    subprocess.run(["emerge", "-cq", "gentoo-sources"])

    # remove leftovers
    for k in leftovers:
        out.einfo(f"removing {out.hilite(k.src.name)}")
        shutil.rmtree(k.src)
        shutil.rmtree(k.modules, ignore_errors=True)
        k.bkp.unlink(missing_ok=True)

@cli
def commit (argv):
    """
    Commit the current kernel config.
    =================================

    Commit the current kernel config with a detailed commit message.

    This command module is a mere wrapper to::

      git add -f /usr/src/linux/.config
      git commit -m "${msg}"

    Command Line Arguments
    ----------------------

    ``-m``
      additional information for the commit message

    ``-n``
      perform a dry run (show what would be commited)

    ``-q``
      be quiet

    """
    msg = io.StringIO()

    def git (argv: list[str]):
        """Run git, capture output and check exit code."""
        return subprocess.run(["git"] + argv, capture_output=True, check=True)

    def summarize (diff: list[str]):
        """Generate the summary of changed options."""
        def changes (s):
            return dict([
                x[1:].split("=", maxsplit=1)
                for x in diff
                if x.startswith(s + "CONFIG") and "CC_VERSION" not in x
            ])
        additions = changes("+")
        deletions = changes("-")
        changes = {
            k: (deletions[k], additions[k])
            for k in additions.keys() & deletions.keys()
        }
        additions = {k: v for k, v in additions.items() if k not in changes}
        deletions = {k: v for k, v in deletions.items() if k not in changes}
        if additions:
            msg.write("\nenabled:\n")
            for opt, val in additions.items():
                msg.write(f"* {opt} = {val}\n")
        if changes:
            msg.write("\nchanged:\n")
            for opt, (old, new) in changes.items():
                msg.write(f"* {opt} = {old} → {new}\n")
        if deletions:
            msg.write("\nremoved:\n")
            for opt, val in deletions.items():
                msg.write(f"* {opt}\n")

    parser = argparse.ArgumentParser(
        prog="ekernel-commit",
        description="Commit the current kernel config.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-m",
        metavar="<msg>",
        dest="msg",
        type=str,
        default="",
        help="additional information for the commit message"
    )
    parser.add_argument(
        "-n",
        dest="dry",
        action="store_true",
        help="perform a dry run (show what would be commited)"
    )
    parser.add_argument(
        "-q",
        dest="quiet",
        action="store_true",
        help="be quiet"
    )
    args = parser.parse_args(argv)
    out.quiet = args.quiet

    # get the kernel under /usr/src/linux
    kernel = Kernel.current()

    # ensure that a config exists
    if not kernel.config.exists():
        raise FileNotFoundError(f"missing config: {kernel.config}")

    # change to source directory
    os.chdir(kernel.src)

    # ensure that we're in a git repository
    try:
        git(["status", "-s"])
    except subprocess.CalledProcessError as e:
        raise RuntimeError(e.stderr.decode().strip())

    # ensure that nothing is staged
    try:
        git(["diff", "--cached", "--exit-code", "--quiet"])
    except subprocess.CalledProcessError as e:
        raise RuntimeError("please commit or stash staged changes")

    # get git root directory
    gitroot = pathlib.Path(
        git(["rev-parse", "--show-toplevel"]).stdout.decode().strip()
    )

    # add unstaged config removals
    removals = [
        gitroot / (l.rsplit(maxsplit=1)[1])
        for l in
            git(["-P", "diff", "--name-status"]).stdout.decode().splitlines()
        if l.startswith("D") and "usr/src/linux" in l and ".config" in l
    ]
    for r in removals: git(["rm", r])

    config_changed = True

    # check if current config is tracked already
    try:
        git(["ls-files", "--error-unmatch", kernel.config])

        # config is tracked: check for changes
        try:
            git(["-P", "diff", "--exit-code", "--quiet", kernel.config])

            # config hasn't changed: only removals remain
            config_changed = False
            if removals:
                msg.write("removed old kernel leftovers")
                if args.msg: msg.write(f"\n\n{args.msg}")

        # config changed
        except subprocess.CalledProcessError:
            git(["add", "-f", kernel.config])
            msg.write("updated kernel config\n")
            if args.msg: msg.write(f"\n{args.msg}\n")
            summarize(
                git(["diff", kernel.config]).stdout.decode().splitlines()
            )

    # config isn't tracked: kernel has been updated
    except subprocess.CalledProcessError:
        git(["add", "-f", kernel.config])

        # /usr/src/linux/.config.old (previous config stored by make oldconfig)
        oldconfig = kernel.src / ".config.old"

        # start header
        msg.write("kernel ")

        # check if .config.old exists
        if oldconfig.exists():
            # get previous version from .config.old, which starts as follows:
            #
            # Automatically generated file; DO NOT EDIT.
            # Linux/x86 X.Y.Z-gentoo Kernel Configuration
            #
            with oldconfig.open() as f:
                f.readline()
                f.readline()
                oldversion = version(f.readline())
                if oldversion.minor != kernel.version.minor:
                    msg.write("upgrade")
                else:
                    msg.write("update")
                msg.write(f": {oldversion} → {kernel.version.base_version}\n")

            # append user's message
            if args.msg: msg.write(f"\n{args.msg}\n")

            # append newly added options (stored in .newoptions)
            newoptions = kernel.src / ".newoptions"
            if newoptions.exists():
                msg.write("\nnew:\n")
                with newoptions.open() as f:
                    for opt in f.readlines():
                        msg.write(f"* {opt.replace('=', ' = ')}")

            # append summary
            summarize(list(difflib.unified_diff(
                oldconfig.read_text().splitlines(),
                kernel.config.read_text().splitlines()
            )))
        else:
            msg.write(f"{kernel.version}")
            if args.msg: msg.write(f"\n\n{args.msg}")

    # print changes
    if removals or config_changed:
        out.einfo("changes to be committed:")
    for l in removals:
        out.print(f"   {colorize('QAWARN', '-')} {out.hilite(l)}")
    if config_changed:
        out.print(f"   {colorize('INFO', '+')} {out.hilite(kernel.config)}")

    # print message
    if msg:
        out.einfo("commit message:")
    for l in msg.getvalue().splitlines():
        out.print(f"   {l}" if l else "")

    # dry run: revert staged changes
    if args.dry:
        git(["restore", "--staged", kernel.config])
        return

    # commit
    try:
        out.ebegin("committing")
        git(["commit", "-m", msg.getvalue()])
        out.eend(0)
    except subprocess.CalledProcessError as e:
        out.eend(1)
        raise RuntimeError(e.stderr.decode())

@cli
@efi
def update (argv):
    """Custom Gentoo EFI stub kernel updater."""
    parser = argparse.ArgumentParser(
        prog="ekernel",
        description="Custom Gentoo EFI stub kernel updater.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-j",
        metavar="<jobs>",
        dest="jobs",
        type=int,
        help=f"number of parallel make jobs (default: {jobs})"
    )
    parser.add_argument(
        "-s",
        metavar="<src>",
        dest="src",
        type=pathlib.Path,
        help="kernel source directory (default: latest)"
    )
    parser.add_argument(
        "-b",
        dest="bkp",
        action="store_true",
        help="create fallback boot entry"
    )
    parser.add_argument(
        "-k",
        metavar="<keep>",
        dest="keep",
        type=int,
        help="keep the previous <num> bootable kernels (default: 1)"
    )
    parser.add_argument(
        "-m",
        metavar="<msg>",
        dest="msg",
        type=str,
        help="additional information for the commit message"
    )
    parser.add_argument(
        "-q",
        dest="quiet",
        action="store_true",
        help="be quiet"
    )
    args = parser.parse_args(argv)
    args.jobs = ["-j", str(args.jobs)] if args.jobs else []
    args.src = ["-s", str(args.src)] if args.src else []
    args.bkp = ["-b"] if args.bkp else []
    args.keep = ["-k", str(args.keep)] if args.keep is not None else []
    args.msg = ["-m", args.msg] if args.msg else []
    args.quiet = ["-q"] if args.quiet else []

    configure(args.quiet + args.src)
    build(args.quiet + args.jobs + args.src)
    install(args.quiet + args.bkp + args.src)
    clean(args.quiet + args.keep)
    commit(args.quiet + args.msg)
