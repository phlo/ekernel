"""Setup the kernel test environment."""
import pathlib
import shutil
import tempfile

from ekernel import Kernel

# create temporary directory
tmpdir = tempfile.TemporaryDirectory()
root = pathlib.Path(tmpdir.name)

# kernel source directory
src = root / "usr/src"

# kernel source symlink
linux = src / "linux"

# kernel module directory
modules = root / "lib/modules"

# EFI system partition
esp = root / "boot/EFI/Gentoo"

# boot image
bootx64 = esp / "bootx64.efi"

# list of installed kernels
kernels = []
sources = [
    src / "linux-5.15.23-gentoo",
    # all except the lastest have been built
    src / "linux-5.15.16-gentoo",
    src / "linux-5.15.3-gentoo",
    src / "linux-5.15.2-gentoo",
    src / "linux-5.15.1-gentoo-r1"
]

# currently installed kernel
current = sources[1]

# latest available kernel
latest = sources[0]

# current config
oldconfig = f"""\
#
# Automatically generated file; DO NOT EDIT.
# Linux/x86 {current}-gentoo Kernel Configuration
#
CONFIG_A=y
CONFIG_B=y
CONFIG_C=y
"""

# new options
newoptions = """\
CONFIG_D=n
CONFIG_E=n
CONFIG_F=n
"""

# new config
newconfig = """\
CONFIG_A=y
CONFIG_C=m
CONFIG_D=y
CONFIG_F=y
"""

def setup ():
    """Setup the kernel test environment."""
    # remove any existing files
    for p in root.glob("*"):
        shutil.rmtree(p)

    # change Kernel class' root directory
    Kernel.src = src
    Kernel.linux = linux
    Kernel.modules = modules
    Kernel.esp = esp
    Kernel.bootx64 = bootx64

    # create EFI system partition
    esp.mkdir(parents=True)

    # create Kernels
    for s in sources: s.mkdir(parents=True)
    global kernels
    kernels = [ Kernel(s) for s in sources ]

    # create config and build files, expect for the latest
    for k in kernels:
        k.bzImage.parent.mkdir(parents=True)
        if k.src == latest: continue
        if k.src == current:
            k.config.write_text(oldconfig)
        else:
            k.config.touch()
        k.bzImage.touch()
        k.efi.touch()
        k.modules.mkdir(parents=True)

    # symlink to old source directory
    linux.symlink_to(current)
