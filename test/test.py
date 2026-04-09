import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge


# ui_in mapping from RTL:
# ui_in[0] = SCL
# ui_in[1] = SDA
def set_i2c_lines(dut, scl, sda):
    dut.ui_in.value = (sda << 1) | scl


async def i2c_clock_pulse(dut, sda):
    set_i2c_lines(dut, 0, sda)
    await ClockCycles(dut.clk, 10)

    set_i2c_lines(dut, 1, sda)
    await ClockCycles(dut.clk, 10)

    set_i2c_lines(dut, 0, sda)
    await ClockCycles(dut.clk, 10)


async def i2c_ack_phase(dut):
    # Master releases SDA, slave drives ACK
    set_i2c_lines(dut, 0, 1)
    await ClockCycles(dut.clk, 10)

    set_i2c_lines(dut, 1, 1)
    await ClockCycles(dut.clk, 10)

    # Optional ACK check
    ack = int(dut.uo_out.value) & 0x02
    dut._log.info(f"ACK raw output bit = {ack}")

    set_i2c_lines(dut, 0, 1)
    await ClockCycles(dut.clk, 10)


async def i2c_write(dut, address, reg_addr, value):
    # Idle bus
    set_i2c_lines(dut, 1, 1)
    await ClockCycles(dut.clk, 10)

    # START: SDA falls while SCL high
    set_i2c_lines(dut, 1, 0)
    await ClockCycles(dut.clk, 10)

    # Address + W bit
    full_addr = (address << 1) | 0
    for i in range(7, -1, -1):
        await i2c_clock_pulse(dut, (full_addr >> i) & 1)

    await i2c_ack_phase(dut)

    # Register address
    for i in range(7, -1, -1):
        await i2c_clock_pulse(dut, (reg_addr >> i) & 1)

    await i2c_ack_phase(dut)

    # Data byte
    for i in range(7, -1, -1):
        await i2c_clock_pulse(dut, (value >> i) & 1)

    await i2c_ack_phase(dut)

    # STOP: SDA rises while SCL high
    set_i2c_lines(dut, 0, 0)
    await ClockCycles(dut.clk, 10)

    set_i2c_lines(dut, 1, 0)
    await ClockCycles(dut.clk, 10)

    set_i2c_lines(dut, 1, 1)
    await ClockCycles(dut.clk, 10)


@cocotb.test()
async def test_i2c_pwm_logic(dut):
    clock = Clock(dut.clk, 10, unit="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut.rst_n.value = 0
    dut.ena.value = 1
    set_i2c_lines(dut, 1, 1)

    await ClockCycles(dut.clk, 5)

    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)

    # -------------------------------
    # Test 1: Duty Cycle = 0x40 (25%)
    # -------------------------------
    dut._log.info("Writing duty_cycle = 0x40")
    await i2c_write(dut, 0x3C, 0x00, 0x40)

    await ClockCycles(dut.clk, 20)

    # Sync to PWM period boundary approximately
    high_count = 0
    for _ in range(256):
        await RisingEdge(dut.clk)
        if int(dut.uo_out.value) & 0x01:
            high_count += 1

    dut._log.info(f"Measured high_count = {high_count}")
    assert 60 <= high_count <= 68, \
        f"Duty cycle mismatch: expected ~64, got {high_count}"

    # -------------------------------
    # Test 2: Prescaler = 4
    # -------------------------------
    dut._log.info("Writing prescaler = 4")
    await i2c_write(dut, 0x3C, 0x01, 0x04)

    await ClockCycles(dut.clk, 20)

    rise_count = 0
    start_time = None
    end_time = None

    while rise_count < 2:
        await RisingEdge(dut.uo_out[0])
        if rise_count == 0:
            start_time = cocotb.utils.get_sim_time(unit="ns")
        elif rise_count == 1:
            end_time = cocotb.utils.get_sim_time(unit="ns")
        rise_count += 1

    period = end_time - start_time
    dut._log.info(f"Measured PWM Period = {period} ns")

    assert 12000 <= period <= 13500, \
        f"Prescaler failed: period={period} ns"
