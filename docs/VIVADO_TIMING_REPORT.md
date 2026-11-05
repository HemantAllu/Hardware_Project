# Vivado timing: NOT VERIFIED

Vivado is not installed in the environment. No timing, utilisation, or bitstream result exists. Do not claim 100 MHz closure.

Run on a machine with Vivado (N is the top-level generic `HFT_N_MAX`; the exact Tcl invocation below is a template that must be adapted to the project scripts and was NOT executed here):
```
for N in 1 2 4 8; do
vivado -mode batch -source build_bitstream.tcl -tclargs HFT_N_MAX=$N   # or set_property generic HFT_N_MAX=$N in create_project.tcl
done
# then in each run:
report_timing_summary -file timing_N$N.rpt
report_utilization    -file util_N$N.rpt
report_clock_utilization
```
Accept only if WNS >= 0 and TNS = 0 for clk = 100 MHz.

Yosys `synth_xilinx` of the flattened N=8 SoC was started but did not finish in the available time (stuck in OPT_DFF on the combinational-read memories), so NO resource or timing estimate exists.
