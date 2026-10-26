module=usb-it950x

PWD = $(shell pwd)
MACHINE = $(shell uname -m)
CURRENT = $(shell uname -r)
INSTALLDIR := /lib/modules/$(CURRENT)/kernel/drivers/media

ifndef KERNELDIR
    KERNELDIR = /lib/modules/$(CURRENT)/build
endif

$(module)-objs := \
		it950x-core.o it950x-drv.o iocontrol.o  \
		tuner.o cmd.o IT9133.o ADF4351.o \
		IT9507.o Omega.o eagleTuner.o \
		standard.o usb2impl.o modulatorUser.o user.o 

obj-m += $(module).o  

default:
	$(MAKE) MYPWD=$(PWD) -C $(KERNELDIR) M=$(PWD) modules

# Kbuild dropped support for EXTRA_CFLAGS in Linux 6.15, use ccflags-y.
# EXTRA_CFLAGS given on the command line is still honored for compatibility.
ccflags-y += $(EXTRA_CFLAGS)
ccflags-y += -DEXPORT_SYMTAB -Wno-unused-value -Wno-unused-variable -Wno-unused-parameter -Wno-switch 

# Build with "make TSDUCK_WRITE=y" for a blocking write(2) (no polling required).
ccflags-$(TSDUCK_WRITE) += -DTSDUCK_WRITE

ifeq "$(MACHINE)" "x86_64"
ccflags-y += -Wno-enum-compare -Wno-int-to-pointer-cast -Wno-array-bounds
endif

install:
	install -d $(INSTALLDIR) 
	install -m 644 -c $(module).ko $(INSTALLDIR)
	/sbin/depmod -a ${KERNELRELEASE}

remove:
	rm -f $(INSTALLDIR)/$(module).ko
	/sbin/modprobe -r $(module)

clean:
	@-rm -rf .tmp_versions *~ *.o *.ko .*.cmd *.mod *.mod.c .cache.mk modules.order Module.markers Module.symvers

-include $(KERNELDIR)/Rules.make
