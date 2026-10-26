# HiDes Linux driver (it950x)

This directory contains the Linux driver for HiDes devices based on the
ITE IT950x chipset, such as the UT-100C USB DVB-T modulator
(USB ID `048d:9507`).

- `it950x_driver/` contains the driver source code. The original sources come
  from ITE, as referenced by the HiDes software page. They were modified to
  build and run on current kernels (tested from 3.10 up to 7.x).
- `config/`, `build-dkms.sh` and `Makefile` build a DKMS package (`.deb` or `.rpm`).
- `60-hides.rules` is the udev rule which gives access to the device to the
  `video` group.
- The original downloaded source archive can be found in `../downloads`.

The driver creates one device node per modulator: `/dev/usb-it950x0`,
`/dev/usb-it950x1`, etc. The kernel module is `usb-it950x.ko` (module name
`usb_it950x`).

## Prerequisites

You need the kernel headers for the running kernel and a C compiler.

```sh
# Ubuntu / Debian
sudo apt install build-essential linux-headers-$(uname -r) dkms

# Fedora / RedHat
sudo dnf install gcc make kernel-devel-$(uname -r) dkms rpm-build rpmdevtools
```

Use the same compiler as the one which built the kernel. The kernel build
system prints `warning: the compiler differs from the one used to build the kernel`
when they differ. A different version of GCC may reject some kernel
compilation options. In that case, select the right compiler with
`CC=gcc-NN` on the `make` command line.

## Option 1: install the DKMS package (recommended)

With DKMS, the driver is automatically rebuilt each time the kernel is upgraded.

Build the package from this directory:

```sh
cd linux-drivers
make
```

The package is created in `linux-drivers/packages/`: a `.deb` on
Ubuntu / Debian / Raspbian, a `.rpm` on RedHat / CentOS / Fedora.
A source tarball `hides-dkms-<version>.tgz` is also created.

Install it:

```sh
# Ubuntu / Debian
sudo apt install ./packages/hides-dkms_*_all.deb

# Fedora / RedHat
sudo dnf install ./packages/hides-dkms-*.noarch.rpm
```

The package installs the sources in `/usr/src/hides-<version>`, builds and
installs the module for the current kernel and installs the udev rule
`/etc/udev/rules.d/60-hides.rules`. Check the result with:

```sh
dkms status
```

To uninstall, remove the package (`sudo apt remove hides-dkms` or
`sudo dnf remove hides-dkms`).

## Option 2: build the module manually

Build against the running kernel:

```sh
cd linux-drivers/it950x_driver
make TSDUCK_WRITE=y
```

To build against another kernel, specify its build directory:

```sh
make TSDUCK_WRITE=y KERNELDIR=/lib/modules/<version>/build
```

Make variables:

| Variable          | Meaning |
|-------------------|---------|
| `TSDUCK_WRITE=y`  | `write(2)` blocks until the device is ready, no polling required. Recommended; the DKMS package always uses it. The driver version then ends with `w` (e.g. `v18.04.16.2w`). |
| `KERNELDIR=...`   | Kernel build directory. Default: `/lib/modules/$(uname -r)/build`. |
| `CC=...`          | Compiler, must match the one which built the kernel. |
| `EXTRA_CFLAGS=...`| Additional compilation flags (still accepted for compatibility, even though recent kernels no longer support this variable themselves). |

Note: older versions of this project used `EXTRA_CFLAGS=-DTSDUCK_WRITE`. Since Linux 6.15,
kbuild ignores `EXTRA_CFLAGS` in Makefiles. Use `TSDUCK_WRITE=y` instead.

Test the module without installing it:

```sh
sudo insmod ./usb-it950x.ko
sudo dmesg | tail -30          # expect "Device_init success"
ls -l /dev/usb-it950x*
cat /sys/module/usb_it950x/version
```

Unload it with `sudo rmmod usb_it950x`.

Install it permanently (it will not be rebuilt on kernel upgrades, use DKMS for that):

```sh
sudo make install                                   # copies to /lib/modules/$(uname -r)/kernel/drivers/media
sudo install -m 644 ../60-hides.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
```

The module has a USB alias for `048d:9507`, it is automatically loaded when
the device is plugged in. To load it manually: `sudo modprobe usb_it950x`.

## Device access

The device node is created as `root:root` with mode `0600` unless the udev
rule is installed. With `60-hides.rules`, the node belongs to the group
`video` with mode `0660`. Add your user to this group:

```sh
sudo usermod -aG video $USER     # then log out and log in again
```

## Secure Boot

When Secure Boot is enabled, the kernel refuses unsigned modules.
On Ubuntu, DKMS signs the module with a local Machine Owner Key (MOK) and asks
you to enroll it at the next reboot. When building manually, sign the module
yourself or disable Secure Boot. Check the state with `mokutil --sb-state`.

## Using the device

The recommended way to use the device is [TSDuck](https://tsduck.io),
which includes HiDes support.

```sh
tshides                                   # list HiDes devices
tshides --gain-range -f 482000000 -b 8    # allowed output gain at a given frequency
```

Example: transmit a transport stream on UHF channel 22 (482 MHz, 8 MHz):

```sh
tsp -I file video.ts --infinite -P regulate \
    -O hides --frequency 482000000 --bandwidth 8 \
    --constellation 64-QAM --high-priority-fec 2/3 \
    --guard-interval 1/32 --transmission-mode 8K --gain 6
```

Always specify `--gain`. With the default output gain, the signal may be too
weak to be received or even visible on a spectrum analyzer. The stream bitrate
must not exceed the modulation capacity (about 24.1 Mb/s with the parameters above).

## Troubleshooting

- `make` fails with `unrecognized command-line option`: the compiler differs from
  the one which built the kernel, use `CC=gcc-NN`.
- No `/dev/usb-it950x*`: check `lsusb | grep 048d`, `lsmod | grep it950x` and
  `dmesg` for `Device_init`.
- `Device RX no initialized` and `no eeprom or DC value is invalid` in `dmesg`
  are normal on the UT-100C, which is a transmitter only.
- `Permission denied` on the device: install the udev rule and join the `video` group.
