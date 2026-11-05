# Running the C programs with `make` (Linux, WSL or Windows Git Bash)

Each `make <name>` compiles `extras/sw/examples/<name>.c` for RV32IM, runs it on the 5-stage core in
Verilog simulation (Vivado xsim or Icarus Verilog, whichever is installed), prints the program's variables and says PASS / FAIL.

## Commands
Run them in a terminal **inside the `rv32im_vivado` folder** (the one with `Makefile`, `src`, `extras`):

| Command | Program |
|---|---|
| `make check` | which tools were found - run this first on a new PC |
| `make add` / `make addition` | ADD, ADDI, overflow, sum 1..100 |
| `make sub` / `make subtract` | SUB, underflow, negation |
| `make xor` | XOR, XORI, NOT, swap, parity |
| `make mul` / `make multiply` | MUL, MULH, MULHU, MULHSU, 10! |
| `make div` / `make divide` | DIV, DIVU, REM, REMU, x/0, INT_MIN/-1 |
| `make sort` / `make sorting` | bubble sort |
| `make fib` / `make fibonacci` | Fibonacci |
| `make gcd`, `make matmul`, `make primes` | other examples |
| `make all` | every program |
| `make list` | program names |
| `make test` | full CPU regression (a few minutes) |
| `make clean` | delete the build files |

Your own program: save it as `extras/sw/examples/myprog.c` (results in global variables, e.g.
`volatile int result[10];`) and run `make myprog`.

Success looks like:
```
 PASS: every register and memory word matches the reference model
 PASS: every result equals the expected value (errors = 0)
```

The Makefile finds Python and the RISC-V compiler by itself (`python3`, `python` or `py`;
`riscv64-unknown-elf-`, `riscv32-unknown-elf-` or `riscv-none-elf-`). To force them:
`make add PYTHON=python RISCV_PREFIX=riscv-none-elf`.

## Windows with Git Bash (same tools as a Vivado lab Makefile): one-time setup
You need: **make**, **Python 3**, the **xPack RISC-V GCC** (`riscv-none-elf-gcc`) and **Vivado**.
No Icarus Verilog is needed: the Makefile uses Vivado's simulator (`xvlog`, `xelab`, `xsim`), the same
commands a Vivado `make` flow runs.  Check in Git Bash:
```
make --version
python --version
riscv-none-elf-gcc --version
xvlog --version
```
If one of them says "command not found":
* **make**: download `make-*-without-guile-w32-bin.zip` from https://sourceforge.net/projects/ezwinports/files/
  and copy its `bin\make.exe` into `C:\Program Files\Git\usr\bin\`.
* **Python**: https://www.python.org/downloads/ (tick "Add python.exe to PATH").
* **RISC-V GCC**: the `win32-x64.zip` from https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases,
  unzipped e.g. to `C:\xpack`.
* **xvlog**: Vivado's `bin` folder is not on Git Bash's PATH.  Find it (e.g. `C:\Xilinx\Vivado\2024.2\bin`,
  `C:\AMDDesignTools\2025.2\Vivado\bin`) and add it, plus the compiler, once:
  ```
  echo 'export PATH="$PATH:/c/Xilinx/Vivado/2024.2/bin:/c/xpack/xpack-riscv-none-elf-gcc-<version>/bin"' >> ~/.bashrc
  source ~/.bashrc
  ```
  (use your real folder names; `C:\` is `/c/` in Git Bash)

Then:
```
cd ~/Downloads/rv32im_vivado_v12_bugfixed/rv32im_vivado     # your folder
make check          # every line "found", and "simulator: xsim"
make add
```
The first run compiles the core with `xvlog` + `xelab` (takes about a minute); later programs reuse
it and only run `xsim`.  If Icarus Verilog is also installed the Makefile prefers it; force Vivado with
`make add SIM=xsim`.  The Vivado logs are in `extras/build_make/xsim/` (`xvlog.out`, `xelab.out`, `xsim.out`).

(Alternative without Vivado: Icarus Verilog from MSYS2 - open "MSYS2 UCRT64", run
`pacman -S mingw-w64-ucrt-x86_64-iverilog`, then add `/c/msys64/ucrt64/bin` to the PATH as above.
If a browser warns about a downloaded installer, do not run it.)

## Linux / WSL: one-time setup
```
sudo apt update
sudo apt install -y make iverilog python3 gcc-riscv64-unknown-elf
cd ~/path/to/rv32im_vivado
make check
make add
```

## Problems
| Message | Fix |
|---|---|
| `bash: make: command not found` | install make (see the Windows section), then reopen Git Bash |
| `make check` says `MISSING a Verilog simulator` | add Vivado's `bin` folder to the PATH (see above), reopen Git Bash, `xvlog --version` must work |
| `ERROR: Vivado compile failed` | read `extras/build_make/xsim/xvlog.out` / `xelab.out` |
| `make check` says `MISSING riscv64-unknown-elf-gcc` | install the RISC-V GCC and add its bin folder to the PATH (Windows section); riscv64-unknown-elf or riscv-none-elf are both found |
| `riscv64-unknown-elf-gcc: command not found` although `riscv-none-elf-gcc --version` works | you have the v12 zip from before 2 Nov: use the newer one (detection now runs in bash, which works with the Windows build of make) |
| `make check` says `MISSING Python 3` | install Python (Windows section); on Windows untick the "python3" App execution alias in Settings if it opens the Store |
| `No rule to make target 'add'` | you are not in the `rv32im_vivado` (or `extras`) folder |
| `$'\r': command not found` | the files got Windows line endings (e.g. via `git clone` with autocrlf). Use the zip, or `git config --global core.autocrlf input` and clone again (the repo's `.gitattributes` keeps scripts LF) |
