# Makefile - run the example C programs on the RV32IM 5-stage core (Verilog simulation)
#
#   make sort       bubble sort of 16 numbers
#   make fib        Fibonacci (loop + recursive)
#   make gcd        greatest common divisor (uses DIV / REM)
#   make matmul     matrix multiply (uses MUL)
#   make primes     prime numbers (uses DIV / REM)
#   make muldiv     MUL/DIV unit testbench (25,152 checks)
#   make all        every example above
#   make test       full regression (tools/run_tests.py)
#   make timing     pipeline table of sw/report_timing.S (the report's timing diagram)
#   make wave-sort  run sort and also write build_make/sort/wave.vcd (open with GTKWave)
#   make clean
#
# Each program: compiled for RV32IM, run on the processor until EBREAK, then its
# variables are printed and checked against the reference model (PASS/FAIL).
# Needs: iverilog, python3, riscv64-unknown-elf-gcc (Linux or WSL).
# Another toolchain prefix:  make sort RISCV_PREFIX=riscv32-unknown-elf

RISCV_PREFIX ?= riscv64-unknown-elf
export RISCV_PREFIX

RTL      := ../src/rtl
CORE_RTL := $(RTL)/alu.v $(RTL)/imm_gen.v $(RTL)/regfile.v $(RTL)/control.v \
            $(RTL)/forwarding_unit.v $(RTL)/hazard_unit.v $(RTL)/muldiv_unit.v \
            $(RTL)/imem.v $(RTL)/dmem.v $(RTL)/rv32im_core.v
B        := build_make
PROGRAMS := sort fib gcd matmul primes

.PHONY: all test clean muldiv timing $(PROGRAMS) $(addprefix wave-,$(PROGRAMS))

all: $(PROGRAMS)

$(B)/tb_core.vvp: tb/tb_core.v $(CORE_RTL)
	@mkdir -p $(B)
	@iverilog -g2005 -o $@ tb/tb_core.v $(CORE_RTL)

# build one program: sw/examples/<name>.c -> build_make/<name>/{imem,dmem}.hex
$(B)/%/imem.hex: sw/examples/%.c sw/crt0.S sw/link.ld
	@bash sw/build.sh $< $(B)/$* > /dev/null
	@[ -s $(B)/$*/dmem.hex ] || echo 00000000 > $(B)/$*/dmem.hex

$(PROGRAMS): %: $(B)/%/imem.hex $(B)/tb_core.vvp
	@vvp -n $(B)/tb_core.vvp +IMEM=$(B)/$*/imem.hex +DMEM=$(B)/$*/dmem.hex 2>&1 \
	    | grep -v 'readmemh' > $(B)/$*/sim.txt
	@python3 tools/show_result.py $(B)/$*/prog.elf $(B)/$*/sim.txt $(B)/$*/imem.hex $(B)/$*/dmem.hex

$(addprefix wave-,$(PROGRAMS)): wave-%: $(B)/%/imem.hex $(B)/tb_core.vvp
	@vvp -n $(B)/tb_core.vvp +IMEM=$(B)/$*/imem.hex +DMEM=$(B)/$*/dmem.hex +VCD=$(B)/$*/wave.vcd 2>&1 \
	    | grep -v 'readmemh' > $(B)/$*/sim.txt
	@python3 tools/show_result.py $(B)/$*/prog.elf $(B)/$*/sim.txt $(B)/$*/imem.hex $(B)/$*/dmem.hex
	@echo " waveform: $(B)/$*/wave.vcd"

timing: $(B)/tb_core.vvp sw/report_timing.S
	@mkdir -p $(B)/timing
	@bash sw/build.sh sw/report_timing.S $(B)/timing > /dev/null
	@[ -s $(B)/timing/dmem.hex ] || echo 00000000 > $(B)/timing/dmem.hex
	@vvp -n $(B)/tb_core.vvp +IMEM=$(B)/timing/imem.hex +DMEM=$(B)/timing/dmem.hex +TRACE 2>&1 \
	    | grep -v 'readmemh' > $(B)/timing/trace.txt
	@python3 tools/pipeline_trace.py $(B)/timing/prog.elf $(B)/timing/trace.txt 0 20

muldiv:
	@mkdir -p $(B)
	@iverilog -g2005 -o $(B)/tb_muldiv.vvp tb/tb_muldiv.v $(RTL)/muldiv_unit.v
	@vvp -n $(B)/tb_muldiv.vvp | grep -E 'checks|PASS|FAIL'

test:
	@python3 tools/run_tests.py

clean:
	rm -rf $(B)
