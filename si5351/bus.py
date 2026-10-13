"""I2C access layer: the real bus (smbus2) and a register-file simulator."""
from .constants import I2C_ADDR, REG_STATUS


class I2CBus:
    """Real I2C access to the SI5351 through smbus2 (/dev/i2c-N on the Pi)."""

    def __init__(self, busnum=1, addr=I2C_ADDR):
        """Open bus `busnum` and check that a chip answers at `addr`.

        Raises ImportError if smbus2 is missing, OSError if no device responds,
        which lets the caller fall back to SimBus.
        """
        from smbus2 import SMBus
        self.bus = SMBus(busnum)
        self.addr = addr
        self.bus.read_byte_data(addr, REG_STATUS)   # raises OSError if no chip

    def write(self, reg, data):
        """Write the bytes in `data` to consecutive registers starting at `reg`."""
        self.bus.write_i2c_block_data(self.addr, reg, list(data))

    def read(self, reg):
        """Read one register byte."""
        return self.bus.read_byte_data(self.addr, reg)


class SimBus:
    """Register file stand-in so the GUI can run without hardware.

    Same write()/read() interface as I2CBus; `regs` can be inspected in tests.
    The `simulated` flag lets the GUI show a banner and skip lock status.
    """
    simulated = True

    def __init__(self):
        """Start with all 256 registers zero (status reads as 'ready, locked')."""
        self.regs = [0] * 256

    def write(self, reg, data):
        """Store the bytes in `data` at consecutive registers from `reg`."""
        for i, v in enumerate(data):
            self.regs[reg + i] = v

    def read(self, reg):
        """Return the stored register byte."""
        return self.regs[reg]
