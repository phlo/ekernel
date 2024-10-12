"""Setup the kernel test environment."""
import functools
import pathlib
import shutil
import subprocess
import tempfile

import ekernel

# create temporary directory
tmpdir = tempfile.TemporaryDirectory()
tmp = pathlib.Path(tmpdir.name)

# kernel source directory
src = tmp / "usr/src"

# kernel source symlink
linux = src / "linux"

# kernel module directory
modules = tmp / "lib/modules"

# EFI system partition (/boot -> /tmp)
esp = tmp.parents[-2]

# boot image
boot = tmp / "boot/EFI/Gentoo/bootx64.efi"

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

def efi (f):
    """Decorator adding common EFI related test actions."""
    @functools.wraps(f)
    def runner (t, *args, **kwargs):
        if args[0][0] == "efibootmgr":
            return subprocess.CompletedProcess("", 0,
                "BootCurrent: 0001\n"
                "Timeout: 1 seconds\n"
                "BootOrder: 0001,0000\n"
                "Boot0000* Windows\tHD()/\\EFI\\Microsoft\\bootmgfw.efi\n"
               f"Boot0001* Gentoo\tHD()/\\EFI\\Gentoo\\{boot.name}\n"
                "Boot0002* Gentoo (ignore)\tHD()/\\EFI\\Gentoo\\ignore.efi\n"
                "Boot0003* Gentoo (fallback)\tHD()/"
                    f"\\EFI\\Gentoo\\{kernels[2].bkp.name}\n"
                .encode()
            )
        elif args[0][0] == "mount":
            ekernel.efi.esp = esp
            ekernel.efi.img = boot
            boot.write_bytes(str(kernels[1].bkp).encode())
            ekernel.efi.bkp["img"] = boot.parent / ekernel.efi.bkp["img"].name
        return f(t, *args, **kwargs)
    return runner

def setup ():
    """Setup the kernel test environment."""
    # remove any existing files
    for p in tmp.glob("*"):
        shutil.rmtree(p)

    # change Kernel paths
    ekernel.Kernel.src = src
    ekernel.Kernel.linux = linux
    ekernel.Kernel.modules = modules

    # change EFI paths
    ekernel.efi.esp = esp
    ekernel.efi.img = boot

    # create EFI system partition
    boot.parent.mkdir(parents=True)

    # create Kernels
    for s in sources: s.mkdir(parents=True)
    global kernels
    kernels = [ ekernel.Kernel(s) for s in sources ]

    # create config and build files, expect for the latest
    for k in kernels:
        k.bzImage.parent.mkdir(parents=True)
        if k.src == latest: continue
        if k.src == current:
            k.config.write_text(oldconfig)
        else:
            k.config.touch()
        k.bzImage.touch()
        k.bkp.write_bytes(str(k.bkp).encode())
        k.modules.mkdir(parents=True)

    # symlink to old source directory
    linux.symlink_to(current)
