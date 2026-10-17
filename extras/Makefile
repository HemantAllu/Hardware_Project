# Makefile - run the example C programs on the RV32IM 5-stage core (Verilog simulation)
#
#   make add        32-bit ADD / ADDI incl. overflow, sum 1..100        (alias: make addition)
#   make sub        32-bit SUB incl. underflow and negation             (alias: make subtract)
#   make xor        XOR / XORI, NOT, swap with three XORs, parity
#   make mul        MUL, MULH, MULHU, MULHSU and 10!                    (alias: make multiply)
#   make div        DIV, DIVU, REM, REMU incl. x/0 and INT_MIN/-1       (alias: make divide)
#   make sort       bubble sort of 16 numbers                          (alias: make sorting)
#   make fib        Fibonacci (loop + recursive)                       (alias: make fibonacci)
#   make gcd        greatest common divisor (uses DIV / REM)
#   make matmul     matrix multiply (uses MUL)
#   make primes     prime numbers (uses DIV / REM)
#   make muldiv     MUL/DIV unit testbench (25,152 checks)
#   make all        every example above
#   make list       the programs you can run
#   make check      which tools were found (run this first on a new PC)
#   SIM=xsim        use Vivado's simulator (xvlog/xelab/xsim) even if Icarus is installed
#   make test       full regression (tools/run_tests.py)
#   make timing     pipeline table of sw/report_timing.S (the report's timing diagram)
#   make wave-sort  run sort and also write build_make/sort/wave.vcd (open with GTKWave)
#   make clean
#
# Each program: compiled for RV32IM, run on the processor until EBREAK, then its
# variables are printed and checked against the reference model (PASS/FAIL).  add, sub, xor,
# mul and div also check every result against the expected value (errors = 0).
# To add your own: put sw/examples/<name>.c here and run  make <name>  (any name works).
# Needs: make, Python 3, a RISC-V GCC and a Verilog simulator: Icarus (iverilog + vvp) OR Vivado
# (xvlog + xelab + xsim on the PATH, as in a Vivado make flow).  Works on Linux, WSL, macOS and
# Windows Git Bash (see README_MAKE.md).  `make check` shows what was found.
# The compiler and Python are found automatically; to force them:
#   make add RISCV_PREFIX=riscv-none-elf   PYTHON=python

# Python 3 and the RISC-V GCC are found by tools/toolenv.sh (python3 / python / py;
# riscv64-unknown-elf / riscv32-unknown-elf / riscv-none-elf ...).  Values given on the command
# line are passed on and used if they work.
export RISCV_PREFIX PYTHON SIM
PY := bash tools/py.sh

# Windows: run the recipes with Git Bash's bash, not cmd.exe
ifeq ($(OS),Windows_NT)
SHELL := bash
endif

RTL      := ../src/rtl
CORE_RTL := $(RTL)/alu.v $(RTL)/imm_gen.v $(RTL)/regfile.v $(RTL)/control.v \
            $(RTL)/forwarding_unit.v $(RTL)/hazard_unit.v $(RTL)/muldiv_unit.v \
            $(RTL)/imem.v $(RTL)/dmem.v $(RTL)/rv32im_core.v
B        := build_make
PROGRAMS := add sub xor mul div sort fib gcd matmul primes

.PHONY: all list check test clean muldiv timing $(PROGRAMS) $(addprefix wave-,$(PROGRAMS)) \
        addition subtract subtraction multiply multiplication divide division sorting fibonacci

all: $(PROGRAMS)

list:
	@echo "programs: $(PROGRAMS)  (run one with: make <name>)"

check:
	@bash tools/check_tools.sh

# friendly names
addition: add
subtract subtraction: sub
multiply multiplication: mul
divide division: div
sorting: sort
fibonacci: fib

# build one program: sw/examples/<name>.c -> build_make/<name>/{imem,dmem}.hex
$(B)/%/imem.hex: sw/examples/%.c sw/crt0.S sw/link.ld
	@bash sw/build.sh $< $(B)/$* > /dev/null

# run it on the core: Icarus Verilog if installed, otherwise Vivado's xvlog/xelab/xsim
# (force one with  make add SIM=xsim  or  SIM=icarus)
$(PROGRAMS): %: $(B)/%/imem.hex
	@bash tools/run_prog.sh $*

# any other sw/examples/<name>.c can be run with  make <name>  too
%: sw/examples/%.c $(B)/%/imem.hex
	@bash tools/run_prog.sh $*

# waveform (Icarus only; with Vivado open the design in the GUI instead)
WAVE = @SIM=icarus bash tools/run_prog.sh $* > /dev/null; \
	vvp -n $(B)/tb_core.vvp +IMEM=$(B)/$*/imem.hex +DMEM=$(B)/$*/dmem.hex +VCD=$(B)/$*/wave.vcd > /dev/null; \
	echo " waveform: $(B)/$*/wave.vcd"
$(addprefix wave-,$(PROGRAMS)): wave-%: $(B)/%/imem.hex
	$(WAVE)
wave-%: sw/examples/%.c $(B)/%/imem.hex
	$(WAVE)

timing: sw/report_timing.S
	@bash sw/build.sh sw/report_timing.S $(B)/timing > /dev/null
	@bash tools/run_prog.sh timing --trace
	@$(PY) tools/pipeline_trace.py $(B)/timing/prog.elf $(B)/timing/trace.txt 0 20

muldiv:
	@bash tools/run_muldiv.sh

test:
	@$(PY) tools/run_tests.py

clean:
	rm -rf $(B)
