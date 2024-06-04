# ekernel - Custom Gentoo EFI Stub Kernel Updater

Automate custom gentoo kernel update tasks.

The update process can roughly be divided into the usual three steps:

1) **configure** - copy and update the previous `.config`
2) **build** - compile the new kernel and install modules
3) **install** - copy the new EFI stub kernel image to the EFI system partition
4) **commit** - commit the new config with a detailed commit message
5) **clean** - remove unused kernel source directories, modules and boot images

This tool aims to minimize the effort by automating the previous steps, while
ensuring maximum flexibility w.r.t. configuration changes.

## Tasks

The following variables will be used throughout this description:

`old` - previous kernel's source directory

`new` - new kernel's source directory

`esp` - directory containing the live kernel image on the EFI system partition (`/boot/EFI/Gentoo/bootx64.efi`)

`jobs` - number of parallel make jobs given by ``-j`` (default: 64)

`version` - new kernel's version string

### `ekernel-configure`

Runs `make menuconfig` if the current config file is missing, or no other kernel is installed

Otherwise, copy the current config file to the new source directory if it doesn't exist (prevent accidental overwrite).

```sh
cp -n ${old}/.config ${new}
```

Get newly added config options and store the result in `${new}/.newoptions`.

```sh
cd ${new}
make listnewconfig > ${new}/.newoptions
```

If ``-l`` was selected: print newly added config options and exit.

```sh
cat ${new}/.newoptions
exit
```

Interactively update the previous config and exit if aborted.

```sh
cd ${new}
make oldconfig || exit
```

### `ekernel-build`

Build and install modules, using the given number of jobs.

```sh
make -j ${jobs} && make modules_install
```

### `ekernel-install`

Update symlink ``/usr/src/linux`` to the new source directory.

```sh
eselect kernel set $(basename ${new})
```

Install the EFI stub kernel image (and a backup copy to revert to in case something breaks after a subsequent kernel update).

```sh
mount /boot
cp ${new}/arch/x86_64/boot/bzImage ${esp}/bootx64.efi
cp ${new}/arch/x86_64/boot/bzImage ${esp}/gentoo-${version}.efi
```

Rebuild external modules.

```sh
emerge @module-rebuild
```

### `ekernel-clean`

Remove unused kernel source directories, modules and boot images.

```sh
emerge --depclean sys-kernel/gentoo-sources
rm -rf $(find /usr/src/ -maxdepth 1 -name "linux-*" | sed -e '/${old}/d' -e '/${new}/d')
rm -rf $(ls -1 /lib/modules/ | sed -e '/${old}/d' -e '/${new}/d')
rm -rf $(ls -1 ${esp} | sed -e '/${old}/d' -e '/${new}/d' -e '/bootx64/d')
```

The default is to keep the previous kernel version in case something goes
horribly wrong.

### `ekernel-commit`

Commit the new kernel config with a detailed commit message.

```sh
git add -f /usr/src/linux/.config
git commit -S -m "${msg}"
```

The message will not only contain the version change, but also details about the newly added or removed options.

## Installation

You may use the ebuild `app-admin/ekernel` from my [personal repository](https://github.com/phlo/phlo-portage).

## Requirements

* [`>=dev-lang/python-3.10`](https://packages.gentoo.org/packages/dev-lang/python)
* [`dev-python/packaging`](https://packages.gentoo.org/packages/dev-python/packaging)
* [`sys-apps/portage`](https://packages.gentoo.org/packages/sys-apps/portage)
